import { idToken } from "./auth.js";

const base = () => (window.TLG_ACADEMY || {}).apiBase || "";

async function call(method, path, body) {
  const token = await idToken();
  if (!token) throw new Error("not logged in");
  const res = await fetch(base() + path, {
    method, headers: { authorization: `Bearer ${token}`, ...(body ? { "content-type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
}

export const me = () => call("GET", "/me");
export const requestAccess = (courseId) => call("POST", `/courses/${courseId}/request`);
export const completeLesson = (courseId, lessonId) => call("POST", `/courses/${courseId}/lessons/${lessonId}/complete`);
export const fileLink = (courseId, fileId) => call("GET", `/courses/${courseId}/files/${fileId}`);
export const adminRequests = (status) => call("GET", `/admin/requests?status=${encodeURIComponent(status)}`);
export const decide = (userId, courseId, decision, note = "") => call("POST", `/admin/requests/${userId}/${courseId}`, { decision, note });

export async function catalogue() {
  const res = await fetch("content/courses.json", { cache: "no-cache" });
  return (await res.json()).courses;
}
export async function lessonMarkdown(file) {
  const res = await fetch(`content/${file}`, { cache: "no-cache" });
  return res.text();
}
