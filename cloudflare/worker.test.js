import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import worker, { dispatch } from "./worker.js";

const env = {
  ENABLED: "true",
  GITHUB_TOKEN: "fake-test-token",
  GITHUB_REPOSITORY: "seirantomo1999-afk/-bot",
  GITHUB_WORKFLOW: "notify.yml",
  GITHUB_REF: "main",
};
const empty = () => Response.json({ total_count: 0, workflow_runs: [] });
const workflowPath = new URL("../.github/workflows/notify.yml", import.meta.url);

test("disabled scheduler makes no requests", async () => {
  assert.deepEqual(await dispatch({}, () => { throw new Error("unexpected request"); }), { status: "disabled" });
  assert.deepEqual(
    await dispatch({ ENABLED: "false", GITHUB_TOKEN: env.GITHUB_TOKEN }, () => { throw new Error("unexpected request"); }),
    { status: "disabled" },
  );
});

test("missing credentials fail without making a request", async () => {
  await assert.rejects(dispatch({ ENABLED: "true" }, () => { throw new Error("unexpected request"); }), /GITHUB_TOKEN is not configured/);
});

test("dispatch posts source only, once, and sends no token in its body", async () => {
  const calls = [];
  const result = await dispatch(env, async (url, init) => {
    calls.push([url, init]);
    return init.method === "POST" ? new Response(null, { status: 204 }) : empty();
  });
  assert.equal(result.status, "accepted");
  assert.equal(calls.filter(([, init]) => init.method === "POST").length, 1);
  assert.equal(calls.filter(([, init]) => init.method !== "POST").length, 5);
  const [url, init] = calls.at(-1);
  assert.equal(url, "https://api.github.com/repos/seirantomo1999-afk/-bot/actions/workflows/notify.yml/dispatches");
  assert.equal(init.headers.Authorization, "Bearer fake-test-token");
  assert.equal(init.headers["User-Agent"], "metro-court-bot-scheduler");
  assert.equal(init.headers["X-GitHub-Api-Version"], "2022-11-28");
  assert.deepEqual(JSON.parse(init.body), { ref: "main", inputs: { source: "cloudflare" } });
  assert.equal(Object.keys(JSON.parse(init.body).inputs).join(), "source");
  assert.equal(init.body.includes(env.GITHUB_TOKEN), false);
  assert.equal(init.body.includes("dry_run"), false);
});

test("a queued or running scan prevents another dispatch", async () => {
  for (const status of ["queued", "in_progress", "waiting", "pending", "requested"]) {
    let posts = 0;
    let seen = 0;
    const result = await dispatch(env, async (url, init) => {
      seen++;
      if (init.method === "POST") {
        posts++;
        return new Response(null, { status: 204 });
      }
      const current = new URL(url).searchParams.get("status");
      return Response.json({ total_count: current === status ? 1 : 0 });
    });
    assert.equal(result.status, "busy");
    assert.equal(posts, 0);
    assert.equal(seen >= 1 && seen <= 5, true);
  }
});

test("failed run check does not attempt POST", async () => {
  let count = 0;
  await assert.rejects(dispatch(env, async () => {
    count++;
    return new Response(null, { status: 403 });
  }), /403/);
  assert.equal(count, 1);
});

test("ambiguous dispatch failure is not retried", async () => {
  let posts = 0;
  await assert.rejects(dispatch(env, async (_, init) => {
    if (init.method !== "POST") return empty();
    posts++;
    throw new Error("timeout after acceptance");
  }), /timeout/);
  assert.equal(posts, 1);
});

test("Cron records a rejected invocation when dispatch fails", async (t) => {
  const errors = [];
  t.mock.method(console, "error", line => errors.push(JSON.parse(line)));
  let pending;
  await worker.scheduled({ scheduledTime: 0 }, { ENABLED: "true" }, {
    waitUntil(promise) { pending = promise; },
  });
  await assert.rejects(pending, /GITHUB_TOKEN is not configured/);
  assert.equal(errors[0].status, "failed");
  assert.equal(errors[0].code, "scheduler_failed");
  assert.equal(JSON.stringify(errors).includes("fake-test-token"), false);
});

test("invalid token and inaccessible workflow have distinct diagnostics", async () => {
  for (const [status, code] of [[401, "github_token_invalid"], [404, "github_resource_unavailable"]]) {
    await assert.rejects(dispatch(env, async () => new Response(null, { status })), error => {
      assert.equal(error.code, code);
      assert.equal(error.operation, "run check");
      assert.equal(error.httpStatus, status);
      assert.equal(error.message.includes(env.GITHUB_TOKEN), false);
      return true;
    });
  }
});

test("permission denial is distinguished from explicit rate limits", async () => {
  for (const [status, headers, code] of [
    [403, {}, "github_access_denied"],
    [403, { "x-ratelimit-remaining": "0" }, "github_rate_limited"],
    [403, { "retry-after": "60" }, "github_rate_limited"],
    [429, {}, "github_rate_limited"],
  ]) {
    await assert.rejects(dispatch(env, async () => new Response(null, { status, headers })), error => {
      assert.equal(error.code, code);
      return true;
    });
  }
});

test("unmerged dispatch inputs fail once with configuration guidance", async () => {
  let posts = 0;
  await assert.rejects(dispatch(env, async (_, init) => {
    if (init.method !== "POST") return empty();
    posts++;
    return new Response(null, { status: 422 });
  }), error => {
    assert.equal(error.code, "github_dispatch_configuration");
    assert.equal(error.operation, "dispatch");
    assert.match(error.message, /default branch/);
    assert.match(error.message, /source input/);
    assert.equal(error.message.includes(env.GITHUB_TOKEN), false);
    return true;
  });
  assert.equal(posts, 1);
});

test("Cron failure log reports the operation without echoing GitHub response data", async (t) => {
  const errors = [];
  t.mock.method(console, "error", line => errors.push(JSON.parse(line)));
  t.mock.method(globalThis, "fetch", async () => new Response(env.GITHUB_TOKEN, { status: 403 }));
  let pending;
  await worker.scheduled({ scheduledTime: 123 }, env, { waitUntil(promise) { pending = promise; } });
  await assert.rejects(pending, /403/);
  assert.deepEqual(errors, [{
    status: "failed",
    scheduledTime: 123,
    code: "github_access_denied",
    operation: "run check",
    httpStatus: 403,
  }]);
  assert.equal(JSON.stringify(errors).includes(env.GITHUB_TOKEN), false);
});

test("Cron logs accepted without the token", async (t) => {
  const logs = [];
  t.mock.method(console, "log", line => logs.push(JSON.parse(line)));
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    if (init?.method === "POST") return new Response(null, { status: 204 });
    return empty();
  });
  let pending;
  await worker.scheduled({ scheduledTime: 99 }, env, { waitUntil(promise) { pending = promise; } });
  await pending;
  assert.deepEqual(logs, [{ status: "accepted", scheduledTime: 99 }]);
  assert.equal(JSON.stringify(logs).includes(env.GITHUB_TOKEN), false);
});

test("worker source does not carry booking controls", () => {
  const source = readFileSync(new URL("./worker.js", import.meta.url), "utf8");
  assert.equal(source.includes("BOOKING_ENABLED"), false);
  assert.equal(source.includes("dry_run"), false);
  assert.equal(/async fetch\s*\(/.test(source), false);
});

function shouldRun({ event, source, mode }) {
  return (event === "schedule" && mode !== "cloudflare") ||
    (event === "workflow_dispatch" && (source !== "cloudflare" || mode === "cloudflare"));
}

test("workflow conditions match the scheduler mode table", () => {
  const workflow = readFileSync(workflowPath, "utf8");
  assert.match(workflow, /name: park_notifier/);
  assert.match(workflow, /options: \[manual, cloudflare\]/);
  assert.match(workflow, /cron: "0,30 22-23,0-15 \* \* \*"/);
  assert.match(workflow, /cancel-in-progress: false/);
  assert.match(workflow, /python gmail\.py/);
  assert.equal(workflow.includes("dry_run"), false);
  assert.match(workflow, /github\.event_name == 'schedule' && vars\.SCHEDULER_MODE != 'cloudflare'/);
  assert.match(workflow, /github\.event_name == 'workflow_dispatch'/);
  assert.match(workflow, /inputs\.source != 'cloudflare' \|\| vars\.SCHEDULER_MODE == 'cloudflare'/);

  const cases = [
    { event: "schedule", source: "", mode: "", run: true },
    { event: "schedule", source: "", mode: "github", run: true },
    { event: "schedule", source: "", mode: "cloudflare", run: false },
    { event: "workflow_dispatch", source: "cloudflare", mode: "", run: false },
    { event: "workflow_dispatch", source: "cloudflare", mode: "github", run: false },
    { event: "workflow_dispatch", source: "cloudflare", mode: "cloudflare", run: true },
    { event: "workflow_dispatch", source: "manual", mode: "", run: true },
    { event: "workflow_dispatch", source: "manual", mode: "github", run: true },
    { event: "workflow_dispatch", source: "manual", mode: "cloudflare", run: true },
  ];
  for (const item of cases) {
    assert.equal(shouldRun(item), item.run, JSON.stringify(item));
  }
});
