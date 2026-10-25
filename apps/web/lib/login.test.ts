import { describe, expect, it } from "vitest";
import { failureText, looksLikeAuthJson, normalizeLoginUrl, tabsFor } from "./login";
import { buildResponse, loginCredentialsFields, loginDoneFields, loginUrlFields } from "./responses";

describe("login card helpers", () => {
  it("offers the tabs the pipeline allows, the window first", () => {
    expect(tabsFor(["upload_state", "credentials", "browser_window"]).map((t) => t.id)).toEqual(["window", "credentials", "upload"]);
    expect(tabsFor(["credentials"]).map((t) => t.id)).toEqual(["credentials"]);
  });

  it("accepts a JSON object as auth.json and nothing else", () => {
    expect(looksLikeAuthJson('{"cookies": [], "origins": []}')).toBe(true);
    expect(looksLikeAuthJson("[1,2]")).toBe(false);
    expect(looksLikeAuthJson("not json")).toBe(false);
    expect(looksLikeAuthJson("null")).toBe(false);
  });

  it("completes a typed login address", () => {
    expect(normalizeLoginUrl(" example.com/login ")).toBe("https://example.com/login");
    expect(normalizeLoginUrl("http://localhost:3000/in")).toBe("http://localhost:3000/in");
    expect(normalizeLoginUrl("ftp://x.com")).toBeNull();
    expect(normalizeLoginUrl("two words")).toBeNull();
    expect(normalizeLoginUrl("")).toBeNull();
  });

  it("shows a failure only when there is one", () => {
    expect(failureText(null)).toBeNull();
    expect(failureText("  ")).toBeNull();
    expect(failureText(" Sai mật khẩu ")).toBe("Sai mật khẩu");
  });
});

describe("login responses", () => {
  const pending = { interaction_id: "int_9", job_id: "j1" };

  it("done carries no secret", () => {
    const r = buildResponse(pending, "login_done", loginDoneFields());
    expect(r.action).toBe("login_done");
    expect(JSON.stringify(r)).not.toMatch(/password|username/i);
  });

  it("a demo account is announced by method only (the secrets go to their own endpoint)", () => {
    const r = buildResponse(pending, "answer", loginCredentialsFields("https://x.com/login"));
    expect(r.answers).toEqual({ login_method: "credentials", login_url: "https://x.com/login" });
    expect(buildResponse(pending, "answer", loginCredentialsFields(null)).answers).toEqual({ login_method: "credentials" });
  });

  it("the typed login address is sent as an answer", () => {
    expect(buildResponse(pending, "answer", loginUrlFields("https://x.com/login")).answers).toEqual({ login_url: "https://x.com/login" });
  });
});
