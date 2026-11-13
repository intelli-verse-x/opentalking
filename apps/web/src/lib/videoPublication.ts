/** Browser orchestration only; every failure attempts to stop both owned jobs. */
export type PublicationState = { status: string; error_code?: string | null };
export type SourcePublicationState = PublicationState & { export_video?: unknown };
const FAILED = new Set(["failed", "error", "stopped", "cancelled"]);
const DONE = new Set(["completed", "done"]);

export function publicationTerminal(status: string | undefined): boolean {
  return Boolean(status && (FAILED.has(status) || DONE.has(status)));
}

export function publicationPause(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException("Publication cancelled", "AbortError")); return; }
    const abort = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      reject(new DOMException("Publication cancelled", "AbortError"));
    };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, 500);
    signal.addEventListener("abort", abort, { once: true });
  });
}

export async function waitForVideoPublication<S extends SourcePublicationState, O extends PublicationState>(options: {
  source: S;
  output: O;
  signal: AbortSignal;
  readSource: (signal: AbortSignal) => Promise<S>;
  readOutput: (signal: AbortSignal) => Promise<O>;
  update: (source: S, output: O) => void;
  stopSource: (signal: AbortSignal) => Promise<unknown>;
  stopOutput: (signal: AbortSignal) => Promise<unknown>;
  pause?: (signal: AbortSignal) => Promise<void>;
  maxPolls?: number;
}): Promise<S> {
  let source = options.source;
  let output = options.output;
  const maxPolls = options.maxPolls ?? 7200;
  if (!Number.isInteger(maxPolls) || maxPolls < 0 || maxPolls > 7200) throw new Error("Invalid publication poll bound");
  const check = () => { if (options.signal.aborted) throw new DOMException("Publication cancelled", "AbortError"); };
  try {
    for (let count = 0; count <= maxPolls; count += 1) {
      check();
      if (FAILED.has(source.status) || FAILED.has(output.status)) {
        throw new Error("Video generation or RTMPS publication failed or stopped");
      }
      if (DONE.has(source.status) && DONE.has(output.status) && source.export_video) return source;
      if (count === maxPolls) break;
      await (options.pause ?? publicationPause)(options.signal);
      check();
      source = await options.readSource(options.signal);
      check();
      output = await options.readOutput(options.signal);
      check();
      options.update(source, output);
    }
    throw new Error("Video/RTMPS completion could not be confirmed before the poll limit");
  } catch (error) {
    await stopPublicationJobs([options.stopOutput, options.stopSource]);
    throw error;
  }
}


export async function stopPublicationJobs(stops: ((signal: AbortSignal) => Promise<unknown>)[]): Promise<void> {
  const cleanup = new AbortController();
  const timer = setTimeout(() => cleanup.abort(), 15000);
  try {
    const results = await Promise.allSettled(stops.map((stop) => Promise.resolve().then(() => stop(cleanup.signal))));
    if (results.some((result) => result.status === "rejected")) {
      throw new Error("Stop requests for all publication jobs could not be confirmed; retry stopping them");
    }
  } finally {
    clearTimeout(timer);
  }
}


export function canStartVideoPublication(activeRun: boolean, sourceStatus?: string, outputStatus?: string): boolean {
  return !activeRun && (sourceStatus === undefined || publicationTerminal(sourceStatus)) && (outputStatus === undefined || publicationTerminal(outputStatus));
}

export function publicationControlsVisible(activePublication: boolean, hasSource: boolean, hasOutput: boolean): boolean {
  return activePublication || hasSource || hasOutput;
}


/** Delayed stop acknowledgements belong only to their original run/attempt. */
export class PublicationOwnership {
  private run = 0;
  private stop = 0;
  beginRun(): void { this.run += 1; this.stop += 1; }
  beginStop(): Readonly<{ run: number; stop: number }> {
    this.stop += 1;
    return Object.freeze({ run: this.run, stop: this.stop });
  }
  ownsStop(ticket: Readonly<{ run: number; stop: number }>): boolean {
    return ticket.run === this.run && ticket.stop === this.stop;
  }
}


export function knownPublicationStatus(job: { status?: unknown } | null): string | undefined {
  if (job === null) return undefined;
  return typeof job.status === "string" && job.status.length > 0 ? job.status : "unknown";
}
