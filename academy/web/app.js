// TLG Academy: a small hash-routed app. Pages: home, courses, course, lesson,
// about, privacy, account, admin. Access to lessons is decided by the API
// (approved enrolment); this file only reflects what the API says.
import * as auth from "./auth.js";
import * as api from "./api.js";

const cfg = window.TLG_ACADEMY || {};
const main = document.getElementById("main");
const state = { courses: [], me: null, loading: true };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const h = (strings, ...vals) => strings.reduce((out, s, i) => out + s + (i < vals.length ? vals[i] : ""), "");
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "");

// ---------------------------------------------------------------- shell
function applyChrome() {
  const inn = auth.loggedIn();
  document.querySelectorAll("[data-when='in']").forEach((el) => (el.hidden = !inn));
  document.querySelectorAll("[data-when='out']").forEach((el) => (el.hidden = inn));
  document.querySelectorAll("[data-admin]").forEach((el) => (el.hidden = !state.me?.is_admin));
  const mail = document.querySelector("[data-contact-email]");
  if (mail) { if (cfg.contactEmail) mail.href = `mailto:${cfg.contactEmail}`; else mail.hidden = true; }
  const phone = document.querySelector("[data-contact-phone]");
  if (phone) phone.textContent = cfg.supportPhone ? ` · ${cfg.supportPhone}` : "";
}
document.querySelectorAll("[data-action='login']").forEach((b) => b.addEventListener("click", () => auth.login()));

function enrolment(courseId) {
  return state.me?.enrolments?.[courseId] || null;
}
function approved(courseId) {
  return enrolment(courseId)?.status === "approved";
}

function cpdStatus(course) {
  // The CPD Group's Accredited Activity badge sits here; while the course is
  // awaiting assessment the "pending" label sits beside it.
  const badgeSrc = course.cpd?.badge || "assets/cpd-accredited-activity.png";
  const register = course.cpd?.register_url || "https://thecpdregister.com/providers/cpd-group-providers--789824";
  const pending = cfg.accreditationPending || !course.cpd?.accreditation_number;
  const label = pending ? h`<span class="badge badge-pending">CPD accreditation pending</span>` : h`<span class="badge badge-ok">CPD accredited</span>`;
  const text = pending
    ? "This course has been submitted to The CPD Group and is awaiting assessment."
    : h`Accredited by The CPD Group, activity number ${esc(course.cpd.accreditation_number)}. <a href="${esc(register)}" target="_blank" rel="noopener">Verify on The CPD Register</a>.`;
  return h`<div class="cpd-status">
    <a href="${esc(register)}" target="_blank" rel="noopener"><img class="cpd-badge" src="${esc(badgeSrc)}" alt="The CPD Group accredited activity badge"></a>
    <div>${label}<p class="small">${text}</p></div></div>`;
}

function cpdStrip() {
  return h`<div class="cpd-strip" aria-label="CPD marks">
    <a href="https://thecpd.group/" target="_blank" rel="noopener"><img src="assets/cpd-group-rosette.png" alt="The CPD Group"></a>
    <a href="https://thecpdregister.com/providers/cpd-group-providers--789824" target="_blank" rel="noopener"><img src="assets/cpd-approved-provider-789824.png" alt="The CPD Group Approved Provider 789824" class="wide"></a>
    <a href="https://thecpdregister.com/providers/cpd-group-providers--789824" target="_blank" rel="noopener"><img src="assets/cpd-register-listed-on.png" alt="Listed on The CPD Register"></a>
  </div>`;
}

// ---------------------------------------------------------------- pages
function pageHome() {
  return h`
    <section class="hero">
      <h1>Learn with The Looking Glass Beauty School</h1>
      <p class="lead">Award-winning nail education in Shrewsbury. Our CPD courses are taught in the salon's training room; this academy holds your pre-course study, the manual and the videos that support the day.</p>
      <div class="btn-row">
        <a class="btn" href="#/courses">See the courses</a>
        ${auth.loggedIn() ? "" : h`<button class="btn btn-secondary" type="button" id="home-signup">Create a student account</button>`}
      </div>
      ${cpdStrip()}
    </section>
    <div class="cards">
      <div class="card"><h2>How it works</h2>
        <ol><li>Create a student account and verify your email.</li><li>Request access to a course. Jess checks you meet the entry requirements.</li><li>Once approved, work through the lessons and download the manual before your taught day.</li></ol></div>
      <div class="card"><h2>Who teaches</h2>
        <p>Jessica Jane Preston: VTCT Level 2 NVQ Diploma in Nail Services, Award in Education and Training, fourteen years in the industry, teaching since 2021 and more than 400 learners trained.</p></div>
    </div>`;
}

function pageCourses() {
  const cards = state.courses.map((c) => {
    const e = enrolment(c.id);
    const tag = c.placeholder ? h`<span class="badge badge-locked">coming soon</span>` : e ? h`<span class="badge ${e.status === "approved" ? "badge-ok" : e.status === "rejected" ? "badge-no" : "badge-pending"}">${esc(e.status)}</span>` : "";
    return h`<div class="card"><h2><a href="#/course/${esc(c.id)}">${esc(c.title)}</a> ${tag}</h2>
      <p>${esc(c.short)}</p>
      <p class="small">${c.placeholder ? "Content to follow" : h`${esc(c.hours)} hours of CPD learning · ${esc(c.lessons.length)} online lessons`} · ${esc(c.delivery)}</p>
      ${cpdStatus(c)}
      <a class="btn btn-secondary btn-small" href="#/course/${esc(c.id)}">Course details</a></div>`;
  }).join("");
  return h`<h1>Courses</h1>${cards || "<p>No courses yet.</p>"}`;
}

function pageCourse(id) {
  const c = state.courses.find((x) => x.id === id);
  if (!c) return "<h1>Course not found</h1>";
  const e = enrolment(id);
  const done = new Set(state.me?.progress?.[id] || []);
  const canLearn = approved(id);
  let access;
  if (c.placeholder) {
    access = h`<div class="notice"><p><strong>Coming soon.</strong> This course is being written. Access requests open when it is published.</p></div>`;
  } else if (!auth.loggedIn()) {
    access = h`<div class="notice"><p><strong>Log in or create an account to request access.</strong> Registering does not open the course; Jess approves each learner against the entry requirements.</p>
      <div class="btn-row"><button class="btn" type="button" data-login>Log in</button><button class="btn btn-secondary" type="button" data-signup>Create an account</button></div></div>`;
  } else if (!e) {
    access = h`<div class="notice"><p><strong>You have not requested access to this course yet.</strong> Request it and Jess will approve or reject it against the entry requirements. You will see the decision here.</p>
      <div class="btn-row"><button class="btn" type="button" data-request="${esc(id)}">Request access</button></div></div>`;
  } else if (e.status === "pending") {
    access = h`<div class="notice"><p><strong>Request sent ${esc(fmtDate(e.requested_at))}.</strong> Waiting for approval. Lessons unlock once Jess has approved you.</p></div>`;
  } else if (e.status === "rejected") {
    access = h`<div class="notice notice-warn"><p><strong>Access was not approved${e.decided_at ? " on " + esc(fmtDate(e.decided_at)) : ""}.</strong> ${e.note ? esc(e.note) : "Please contact the school if you think the entry requirements are met."}</p>
      <div class="btn-row"><button class="btn btn-secondary" type="button" data-request="${esc(id)}">Request again</button></div></div>`;
  } else {
    access = h`<div class="notice notice-ok"><p><strong>You are approved for this course.</strong> ${done.size} of ${c.lessons.length} lessons complete.</p></div>`;
  }
  const files = (c.files || []).map((f) => h`<button class="btn btn-secondary btn-small" type="button" data-file="${esc(id)}:${esc(f.id)}" ${canLearn ? "" : "disabled"}>${esc(f.label)}</button>`).join(" ");
  const lessons = c.lessons.map((l, i) => {
    const cls = done.has(l.id) ? "done" : canLearn ? "" : "locked";
    const inner = h`<span class="lesson-num ${cls}" aria-hidden="true">${i + 1}</span><span>${esc(l.title)}</span><span class="lesson-meta">${esc(l.minutes)} min${done.has(l.id) ? " · done" : ""}</span>`;
    return canLearn ? h`<li><a class="lesson-link" href="#/course/${esc(id)}/lesson/${esc(l.id)}">${inner}</a></li>`
      : h`<li><span class="lesson-link muted" aria-label="${esc(l.title)}, locked">${inner}</span></li>`;
  }).join("");
  return h`
    <h1>${esc(c.title)}</h1>
    <p class="lead">${esc(c.short)}</p>
    ${cpdStatus(c)}
    ${cpdStrip()}
    ${access}
    <dl class="facts">
      <dt>Delivery</dt><dd>${esc(c.delivery)}</dd>
      <dt>Duration</dt><dd>${esc(c.hours)} hours: ${esc(c.hours_breakdown)}</dd>
      <dt>Entry requirements</dt><dd>${esc(c.prerequisites)}</dd>
      <dt>Assessment</dt><dd>${esc(c.assessment)}</dd>
      <dt>Certificate</dt><dd>Issued by The Looking Glass Beauty School after the taught day, the practical and the case studies. Not issued by this website.</dd>
    </dl>
    <h2>Learning outcomes</h2>
    <ul>${c.outcomes.map((o) => h`<li>${esc(o)}</li>`).join("")}</ul>
    <h2>Course files</h2>
    <p>${files || "None yet."}${canLearn ? "" : h` <span class="small">Available once approved.</span>`}</p>
    <h2>Online lessons</h2>
    <ul class="lessons">${lessons}</ul>`;
}

async function pageLesson(courseId, lessonId) {
  const c = state.courses.find((x) => x.id === courseId);
  const idx = c ? c.lessons.findIndex((l) => l.id === lessonId) : -1;
  if (!c || idx < 0) return "<h1>Lesson not found</h1>";
  if (!approved(courseId)) return h`<h1>${esc(c.lessons[idx].title)}</h1><div class="notice notice-warn"><p>This lesson is available once your access to the course is approved.</p><p><a href="#/course/${esc(courseId)}">Back to the course</a></p></div>`;
  const l = c.lessons[idx];
  const md = await api.lessonMarkdown(l.file);
  const html = window.marked ? window.marked.parse(md) : `<pre>${esc(md)}</pre>`;
  const video = l.youtube_id
    ? h`<div class="video"><iframe src="https://www.youtube-nocookie.com/embed/${esc(l.youtube_id)}?rel=0" title="${esc(l.title)}" allow="accelerometer; encrypted-media; picture-in-picture" allowfullscreen loading="lazy"></iframe></div>`
    : h`<div class="video" role="img" aria-label="Video placeholder"><div class="video-placeholder"><strong>Video coming soon</strong><span class="small">A placeholder until the lesson video is added (set youtube_id in courses.json).</span></div></div>`;
  const done = (state.me?.progress?.[courseId] || []).includes(lessonId);
  const prev = c.lessons[idx - 1], next = c.lessons[idx + 1];
  return h`
    <p class="small"><a href="#/course/${esc(courseId)}">${esc(c.title)}</a> · Lesson ${idx + 1} of ${c.lessons.length}</p>
    <h1>${esc(l.title)}</h1>
    ${video}
    <article class="prose">${html}</article>
    <div class="btn-row">${done ? h`<span class="badge badge-ok">Completed</span>` : h`<button class="btn" type="button" data-complete="${esc(courseId)}:${esc(lessonId)}">Mark lesson complete</button>`}</div>
    <nav class="lesson-nav" aria-label="Lessons">
      ${prev ? h`<a class="btn btn-secondary" href="#/course/${esc(courseId)}/lesson/${esc(prev.id)}">Previous: ${esc(prev.title)}</a>` : "<span></span>"}
      ${next ? h`<a class="btn btn-secondary" href="#/course/${esc(courseId)}/lesson/${esc(next.id)}">Next: ${esc(next.title)}</a>` : h`<a class="btn" href="#/course/${esc(courseId)}">Back to the course</a>`}
    </nav>`;
}

function pageAbout() {
  return h`
    <h1>About the school</h1>
    <p>The Looking Glass Beauty School is the training arm of The Looking Glass, an independent salon in Shrewsbury. Our courses are written and taught by Jessica Jane Preston, a qualified nail professional and educator (VTCT Level 2 NVQ Diploma in Nail Services, Award in Education and Training), and are delivered in the salon's own training room.</p>
    <h2>Continuing professional development</h2>
    ${cpdStrip()}
    <p>The school is an approved provider with The CPD Group (provider number 789824). Approved provider status means the school has met The CPD Group's provider criteria; it does not mean a course is accredited. Each course is assessed on its own merit against The CPD Group's ACCREDITED framework, and each course page shows its own status. Accredited courses can be verified on The CPD Register.</p>
    <h2>How a course runs</h2>
    <p>Our CPD courses are classroom courses. The academy holds the pre-course study, the learner manual and the support videos, and records which lessons you have completed. Assessment, the practical on a model and your certificate all happen through the school, not this website.</p>
    <h2>Accessibility</h2>
    <p>Tell us about any additional learning, accessibility or support needs when you request access, or at any time. We provide large-print and digital materials, extra time for assessments, one-to-one support and other reasonable adjustments. The salon and training room are wheelchair accessible.</p>`;
}

function pagePrivacy() {
  return h`
    <h1>Privacy notice</h1>
    <p><strong>Who we are.</strong> TLG Beauty Limited, trading as The Looking Glass Beauty School, 4a Roushill, Shrewsbury SY1 1PQ, is the data controller for this academy.</p>
    <p><strong>What we collect.</strong> When you create an account: your name and email address, held by Amazon Cognito in the EU (London region) on our behalf. When you use the academy: which courses you have requested, the decision on each request, which lessons you have completed, and the dates. Nothing else; no analytics, no advertising cookies.</p>
    <p><strong>Why.</strong> To give you access to course materials you are approved for, to check entry requirements, and to keep the records a training provider is expected to keep. The lawful basis is our contract with you as a learner and our legitimate interest in running the school.</p>
    <p><strong>Cookies and storage.</strong> The site stores your login tokens in your browser's session storage for the time you are logged in. It sets no tracking cookies. Videos are embedded from YouTube in privacy-enhanced mode; YouTube's own notice applies when you play one.</p>
    <p><strong>Sharing.</strong> We do not sell or share your details. Amazon Web Services processes them on our behalf. If a course is CPD accredited, your certificate details may be verified through The CPD Group's register in line with their notice.</p>
    <p><strong>Retention.</strong> Account and progress records are kept while your account is active and for six years after your last course, to match the school's training records, then deleted.</p>
    <p><strong>Your rights.</strong> You can ask for a copy of your data, correct it, or ask for your account to be deleted by emailing ${cfg.contactEmail ? h`<a href="mailto:${esc(cfg.contactEmail)}">${esc(cfg.contactEmail)}</a>` : "the school"}. You can complain to the Information Commissioner's Office at ico.org.uk.</p>`;
}

function pageAccount() {
  if (!auth.loggedIn()) return h`<h1>Account</h1><p>You are not logged in.</p><div class="btn-row"><button class="btn" type="button" data-login>Log in</button><button class="btn btn-secondary" type="button" data-signup>Create an account</button></div>`;
  const u = state.me?.user || auth.claims() || {};
  const rows = Object.entries(state.me?.enrolments || {}).map(([cid, e]) => {
    const c = state.courses.find((x) => x.id === cid);
    return h`<tr><td data-label="Course">${esc(c?.title || cid)}</td><td data-label="Status"><span class="badge ${e.status === "approved" ? "badge-ok" : e.status === "rejected" ? "badge-no" : "badge-pending"}">${esc(e.status)}</span></td><td data-label="Requested">${esc(fmtDate(e.requested_at))}</td></tr>`;
  }).join("");
  return h`
    <h1>Your account</h1>
    <dl class="facts"><dt>Name</dt><dd>${esc(u.name)}</dd><dt>Email</dt><dd>${esc(u.email)}</dd>${state.me?.is_admin ? "<dt>Role</dt><dd>Administrator</dd>" : ""}</dl>
    <h2>Your courses</h2>
    ${rows ? h`<table class="table"><thead><tr><th>Course</th><th>Status</th><th>Requested</th></tr></thead><tbody>${rows}</tbody></table>` : "<p>You have not requested access to a course yet. <a href='#/courses'>See the courses</a>.</p>"}
    <div class="btn-row"><button class="btn btn-secondary" type="button" data-logout>Log out</button></div>
    <p class="small">To change your password, log out and use "Forgot your password?" on the login page. To delete your account, email the school.</p>`;
}

async function pageAdmin(status = "pending") {
  if (!state.me?.is_admin) return "<h1>Approvals</h1><p>This page is for the school's administrators.</p>";
  const data = await api.adminRequests(status);
  const rows = data.requests.map((r) => {
    const c = state.courses.find((x) => x.id === r.course_id);
    const actions = status === "approved" ? h`<button class="btn btn-danger btn-small" type="button" data-decide="${esc(r.user_id)}:${esc(r.course_id)}:rejected">Revoke</button>`
      : status === "rejected" ? h`<button class="btn btn-small" type="button" data-decide="${esc(r.user_id)}:${esc(r.course_id)}:approved">Approve</button>`
      : h`<button class="btn btn-small" type="button" data-decide="${esc(r.user_id)}:${esc(r.course_id)}:approved">Approve</button> <button class="btn btn-danger btn-small" type="button" data-decide="${esc(r.user_id)}:${esc(r.course_id)}:rejected">Reject</button>`;
    return h`<tr><td data-label="Learner">${esc(r.name)}<br><span class="small">${esc(r.email)}</span></td><td data-label="Course">${esc(c?.title || r.course_id)}</td><td data-label="Requested">${esc(fmtDate(r.requested_at))}${r.decided_at ? h`<br><span class="small">decided ${esc(fmtDate(r.decided_at))}</span>` : ""}</td><td data-label="Action">${actions}</td></tr>`;
  }).join("");
  const tab = (s, label) => h`<button type="button" role="tab" aria-selected="${s === status}" data-admin-tab="${s}">${label}</button>`;
  return h`
    <h1>Course access approvals</h1>
    <p class="small">Approving unlocks the lessons and the manual for that learner. Rejecting leaves a note they can see; they may request again. Check the entry requirements on the course page before approving.</p>
    <div class="tabs" role="tablist">${tab("pending", "Pending")}${tab("approved", "Approved")}${tab("rejected", "Rejected")}</div>
    ${rows ? h`<table class="table"><thead><tr><th>Learner</th><th>Course</th><th>Requested</th><th>Action</th></tr></thead><tbody>${rows}</tbody></table>` : h`<p>Nothing ${esc(status)}.</p>`}`;
}

// ---------------------------------------------------------------- router
async function render() {
  const hash = location.hash || "#/";
  const parts = hash.slice(2).split("/").filter(Boolean);
  let html;
  try {
    if (parts.length === 0) html = pageHome();
    else if (parts[0] === "courses") html = pageCourses();
    else if (parts[0] === "course" && parts[2] === "lesson") html = await pageLesson(parts[1], parts[3]);
    else if (parts[0] === "course") html = pageCourse(parts[1]);
    else if (parts[0] === "about") html = pageAbout();
    else if (parts[0] === "privacy") html = pagePrivacy();
    else if (parts[0] === "account") html = pageAccount();
    else if (parts[0] === "admin") html = await pageAdmin(parts[1] || "pending");
    else html = "<h1>Page not found</h1>";
  } catch (err) {
    html = h`<div class="notice notice-warn"><p><strong>Something went wrong.</strong> ${esc(err.message)}</p></div>`;
  }
  main.innerHTML = html;
  main.querySelector("h1")?.setAttribute("tabindex", "-1");
  window.scrollTo(0, 0);
  applyChrome();
}

async function refreshMe() {
  if (!auth.loggedIn() || !cfg.apiBase) { state.me = null; return; }
  try { state.me = await api.me(); } catch (err) { console.warn("me failed", err); state.me = null; }
}

main.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button");
  if (!t) return;
  try {
    if (t.hasAttribute("data-login")) return auth.login();
    if (t.hasAttribute("data-signup") || t.id === "home-signup") return auth.signup();
    if (t.hasAttribute("data-logout")) return auth.logout();
    if (t.dataset.request) { t.disabled = true; await api.requestAccess(t.dataset.request); await refreshMe(); return render(); }
    if (t.dataset.complete) { const [c, l] = t.dataset.complete.split(":"); t.disabled = true; await api.completeLesson(c, l); await refreshMe(); return render(); }
    if (t.dataset.file) { const [c, f] = t.dataset.file.split(":"); t.disabled = true; const { url } = await api.fileLink(c, f); window.open(url, "_blank", "noopener"); t.disabled = false; return; }
    if (t.dataset.decide) { const [u, c, d] = t.dataset.decide.split(":"); const note = d === "rejected" ? (prompt("Reason the learner will see (optional):") || "") : ""; t.disabled = true; await api.decide(u, c, d, note); return render(); }
    if (t.dataset.adminTab) { location.hash = `#/admin/${t.dataset.adminTab}`; }
  } catch (err) {
    alert(err.message);
    t.disabled = false;
  }
});

window.addEventListener("hashchange", render);

(async function start() {
  try {
    const returnTo = await auth.completeLogin();
    if (returnTo) location.hash = returnTo;
  } catch (err) {
    console.warn(err);
  }
  state.courses = await api.catalogue().catch(() => []);
  await refreshMe();
  applyChrome();
  render();
})();
