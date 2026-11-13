import assert from "node:assert/strict";
import test from "node:test";
import { mediaRequestCredentials, whepResource, deleteWhepResource, receiverCanStop } from "../src/lib/streamingSecurity.ts";

const page = "https://studio.example.invalid/";
const media = "https://media.example.invalid:8889/live/master.m3u8";
const synthetic = "Basic synthetic-only";

test("HLS relative segments retain auth only on the selected media origin", () => {
  assert.deepEqual(mediaRequestCredentials(media, "segments/one.m4s", page, synthetic), {
    withCredentials: true, authorization: synthetic,
  });
  assert.deepEqual(mediaRequestCredentials("/streaming/hls/master.m3u8", "/streaming/hls/one.m4s", page, synthetic), {
    withCredentials: true, authorization: synthetic,
  });
});

for (const target of [
  "https://foreign.example.invalid/segment", "//foreign.example.invalid/key",
  "https://media.example.invalid/live/segment", "http://media.example.invalid:8889/segment",
  "https://injected:password@media.example.invalid:8889/segment", "data:text/plain,segment",
]) {
  test(`HLS never forwards reader auth/cookies to another boundary: ${target}`, () => {
    assert.deepEqual(mediaRequestCredentials(media, target, page, synthetic), {
      withCredentials: false, authorization: null,
    });
  });
}

test("HLS invalid or credential-embedded source is not authorized", () => {
  for (const source of ["https://[", "https://user:secret@media.example.invalid:8889/master.m3u8", "data:text/plain,source"]) {
    assert.deepEqual(mediaRequestCredentials(source, "https://media.example.invalid:8889/segment", page, synthetic), {
      withCredentials: false, authorization: null,
    });
  }
});

test("WHEP relative Location captures the original session token immutably", async () => {
  let token = "synthetic-original";
  const resource = whepResource("https://media.example.invalid/whep", "/session/one", token);
  token = "synthetic-edited-after-start";
  assert(Object.isFrozen(resource));
  const calls: { input: unknown; init: RequestInit | undefined }[] = [];
  await deleteWhepResource(resource, (async (input, init) => {
    calls.push({ input, init }); return new Response(null, { status: 204 });
  }) as typeof fetch);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].input, "https://media.example.invalid/session/one");
  assert.deepEqual(calls[0].init?.headers, { Authorization: "Bearer synthetic-original" });
  assert.equal(calls[0].init?.redirect, "error");
  assert.equal(token, "synthetic-edited-after-start");
});

for (const location of [
  "https://foreign.example.invalid/session", "//foreign.example.invalid/session",
  "http://media.example.invalid/session", "https://media.example.invalid:444/session",
  "https://user:password@media.example.invalid/session", "/session#fragment",
]) {
  test(`WHEP rejects an untrusted Location without issuing a request: ${location}`, () => {
    assert.throws(() => whepResource("https://media.example.invalid/whep", location, "synthetic"));
  });
}

test("WHEP cleanup also runs for a session without a bearer", async () => {
  const resource = whepResource("https://media.example.invalid/whep", "session/one", "");
  await deleteWhepResource(resource, (async (_input, init) => {
    assert.deepEqual(init?.headers, {}); assert.equal(init?.redirect, "error");
    return new Response(null, { status: 204 });
  }) as typeof fetch);
});

test("WHEP remote cleanup errors do not escape local teardown", async () => {
  await deleteWhepResource(whepResource("https://media.example.invalid/whep", "/session/one", "synthetic"),
    (async () => { throw new Error("synthetic network failure"); }) as typeof fetch);
});


test("HLS same-origin HTTP development proxy remains usable", () => {
  assert.deepEqual(mediaRequestCredentials("/streaming/hls/master.m3u8", "/streaming/hls/one.m4s", "http://127.0.0.1:5173/", synthetic), {
    withCredentials: true, authorization: synthetic,
  });
});

test("HLS does not send credentials to a remote cleartext source", () => {
  assert.deepEqual(mediaRequestCredentials("http://media.example.invalid/live/master.m3u8", "segment.m4s", page, synthetic), {
    withCredentials: false, authorization: null,
  });
});


test("an ICE failure cannot hide Stop while peer or server session remains owned", () => {
  assert(receiverCanStop("error", true, true));
  assert(receiverCanStop("error", true, false));
  assert(receiverCanStop("error", false, true));
  assert(!receiverCanStop("idle", false, false));
});
