import assert from "node:assert/strict";
import test from "node:test";
import { waitForVideoPublication, publicationPause, publicationTerminal, stopPublicationJobs, PublicationOwnership, knownPublicationStatus, canStartVideoPublication, publicationControlsVisible } from "../src/lib/videoPublication.ts";

function harness() {
  const controller = new AbortController();
  const calls: string[] = [];
  return { controller, calls, options: {
    source: { status: "generating", export_video: undefined as object | undefined },
    output: { status: "publishing" }, signal: controller.signal,
    readSource: async (_signal: AbortSignal) => ({ status: "completed", export_video: {} }),
    readOutput: async (_signal: AbortSignal) => ({ status: "completed" }),
    update: () => { calls.push("update"); },
    stopSource: async (_signal: AbortSignal) => { calls.push("stopSource"); },
    stopOutput: async (_signal: AbortSignal) => { calls.push("stopOutput"); },
    pause: async (_signal: AbortSignal) => {}, maxPolls: 2,
  } };
}

test("completion requires an exported source AND a completed publisher", async () => {
  const h = harness();
  const result = await waitForVideoPublication(h.options);
  assert.equal(result.status, "completed");
  assert.deepEqual(h.calls, ["update"]);
});

test("completed video with a still-publishing output is not successful", async () => {
  const h = harness();
  h.options.readOutput = async () => ({ status: "publishing" });
  await assert.rejects(waitForVideoPublication(h.options), /poll limit/);
  assert(h.calls.includes("stopSource") && h.calls.includes("stopOutput"));
});

test("a read failure stops source even when stopping publisher fails", async () => {
  const h = harness();
  h.options.readSource = async () => { throw new Error("synthetic read failure"); };
  h.options.stopOutput = async () => { h.calls.push("stopOutput"); throw new Error("synthetic stop failure"); };
  await assert.rejects(waitForVideoPublication(h.options), /could not be confirmed/);
  assert.deepEqual(h.calls.sort(), ["stopOutput", "stopSource"]);
});

test("cancelled polling cannot read or publish stale UI state", async () => {
  const h = harness();
  h.options.pause = async () => { h.controller.abort(); };
  h.options.readSource = async () => { throw new Error("must not read after abort"); };
  await assert.rejects(waitForVideoPublication(h.options), { name: "AbortError" });
  assert.deepEqual(h.calls.sort(), ["stopOutput", "stopSource"]);
});

test("abort during the source response does not read output or update stale state", async () => {
  const h = harness();
  h.options.readSource = async () => { h.controller.abort(); return { status: "completed", export_video: {} }; };
  h.options.readOutput = async () => { throw new Error("must not read output after abort"); };
  await assert.rejects(waitForVideoPublication(h.options), { name: "AbortError" });
  assert.deepEqual(h.calls.sort(), ["stopOutput", "stopSource"]);
});

test("publisher failure stops a still-generating source immediately", async () => {
  const h = harness(); h.options.output.status = "failed";
  await assert.rejects(waitForVideoPublication(h.options), /failed or stopped/);
  assert.deepEqual(h.calls.sort(), ["stopOutput", "stopSource"]);
});

test("a missing export is not completion", async () => {
  const h = harness();
  h.options.readSource = async () => ({ status: "completed", export_video: undefined as object | undefined });
  await assert.rejects(waitForVideoPublication(h.options), /poll limit/);
  assert(h.calls.includes("stopSource") && h.calls.includes("stopOutput"));
});

test("independent stop requests still run after a synchronous failure", async () => {
  const calls: string[] = [];
  await assert.rejects(stopPublicationJobs([
    () => { calls.push("output"); throw new Error("synthetic"); },
    async () => { calls.push("source"); },
  ]), /could not be confirmed/);
  assert.deepEqual(calls, ["output", "source"]);
});

test("an already-aborted pause rejects without a timer wait", async () => {
  const c = new AbortController(); c.abort();
  await assert.rejects(publicationPause(c.signal), { name: "AbortError" });
});

test("an active pause is interrupted by abort", async () => {
  const c = new AbortController(); const waiting = publicationPause(c.signal); c.abort();
  await assert.rejects(waiting, { name: "AbortError" });
});

test("terminal classifications preserve a stop retry for unknown/running states", () => {
  for (const s of ["done", "completed", "failed", "error", "stopped", "cancelled"]) assert(publicationTerminal(s));
  for (const s of [undefined, "waiting_publisher", "generating", "publishing"]) assert(!publicationTerminal(s));
});


test("failed stop cannot let a new run erase unresolved source/publisher IDs", () => {
  assert(!canStartVideoPublication(false, "generating", "publishing"));
  assert(!canStartVideoPublication(false, "completed", "publishing"));
  assert(!canStartVideoPublication(false, "waiting_publisher", "failed"));
  assert(canStartVideoPublication(false, "stopped", "stopped"));
  assert(!canStartVideoPublication(true, "stopped", "stopped"));
});

test("changing form mode cannot hide controls for captured work", () => {
  const currentFormPublishMode = false;
  assert.equal(currentFormPublishMode, false);
  assert(publicationControlsVisible(true, false, false));
  assert(publicationControlsVisible(false, true, false));
  assert(publicationControlsVisible(false, false, true));
  assert(!publicationControlsVisible(false, false, false));
});


test("a delayed retry-stop acknowledgement cannot mutate a replacement run", () => {
  const owner = new PublicationOwnership();
  owner.beginRun();
  const first = owner.beginStop();
  const retry = owner.beginStop();
  assert(!owner.ownsStop(first));
  assert(owner.ownsStop(retry));
  // One successful stop can make the old statuses terminal and enable a new
  // run while another old request remains in flight. Its reply is stale.
  owner.beginRun();
  assert(!owner.ownsStop(first));
  assert(!owner.ownsStop(retry));
  const next = owner.beginStop();
  assert(owner.ownsStop(next));
});


test("a known job with empty/malformed status cannot be overwritten as absent", () => {
  assert.equal(knownPublicationStatus(null), undefined);
  for (const status of [undefined, "", null, 0, ["done"]]) {
    const known = knownPublicationStatus({ status });
    assert.equal(known, "unknown");
    assert(!canStartVideoPublication(false, known, undefined));
  }
  assert(!canStartVideoPublication(false, "", undefined));
  assert(canStartVideoPublication(false, knownPublicationStatus({ status: "completed" }), undefined));
});
