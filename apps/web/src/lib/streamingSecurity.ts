/** Bind media credentials to the explicitly selected origin, never playlist URLs. */
export function mediaRequestCredentials(
  source: string,
  request: string,
  pageUrl: string,
  authorization: string | null,
): { withCredentials: boolean; authorization: string | null } {
  try {
    const base = new URL(source, pageUrl);
    const target = new URL(request, base);
    const page = new URL(pageUrl);
    const secureSource = base.protocol === "https:" || (base.protocol === "http:" && base.origin === page.origin);
    const trusted = secureSource
      && target.origin === base.origin
      && target.protocol === base.protocol
      && !base.username && !base.password && !target.username && !target.password;
    return { withCredentials: trusted, authorization: trusted ? authorization : null };
  } catch {
    return { withCredentials: false, authorization: null };
  }
}

export type WhepResource = Readonly<{ url: string; authorization: string | null }>;

export function whepResource(endpoint: string, location: string, token: string): WhepResource {
  const base = new URL(endpoint);
  const target = new URL(location, base);
  if (base.protocol !== "https:" || target.origin !== base.origin
    || target.protocol !== "https:" || base.username || base.password
    || target.username || target.password || target.hash) {
    throw new Error("WHEP session Location must remain on the selected HTTPS origin");
  }
  return Object.freeze({ url: target.toString(), authorization: token.trim() ? `Bearer ${token.trim()}` : null });
}

/** Best-effort remote cleanup must never delay closing local media resources. */
export async function deleteWhepResource(resource: WhepResource, fetcher: typeof fetch = fetch): Promise<void> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    await fetcher(resource.url, {
      method: "DELETE",
      headers: resource.authorization ? { Authorization: resource.authorization } : {},
      redirect: "error",
      signal: controller.signal,
    });
  } catch {
    // Local peer/tracks are already closed; credentials are never logged.
  } finally {
    clearTimeout(timer);
  }
}


export function receiverCanStop(state: string, hasPeer: boolean, hasResource: boolean): boolean {
  return hasPeer || hasResource || state === "connecting" || state === "live";
}
