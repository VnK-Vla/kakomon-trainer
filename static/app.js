const DEFAULT_USER_NAME = "自分";
const USER_STORAGE_KEY = "kakomon-trainer-user";
const LIBRARY_PAGE_SIZE = 40;
const QUESTION_ATTEMPT_HISTORY_LIMIT = 30;
const COMPACT_FILTER_MEDIA = "(max-width: 520px)";

function normalizeUserName(value) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text || DEFAULT_USER_NAME;
}

function storedUserName() {
  try {
    return normalizeUserName(window.localStorage.getItem(USER_STORAGE_KEY));
  } catch {
    return DEFAULT_USER_NAME;
  }
}

const RANDOM_START_STORAGE_KEY = "kakomon-trainer-random-start";

function storedRandomStart() {
  try {
    return window.localStorage.getItem(RANDOM_START_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

const state = {
  questions: [],
  allQuestions: [],
  studyQuestions: [],
  studySummary: null,
  questionsLoaded: false,
  users: [],
  stats: null,
  session: { mode: "direct", can_switch_user: true, can_manage_users: false, can_edit_questions: false },
  currentUser: storedUserName(),
  currentQuestion: null,
  currentIndex: -1,
  activeTab: "practice",
  selectedExam: "放射線診断専門医認定試験",
  studyMode: "category",
  showStudyMap: true,
  studyItems: [],
  libraryPage: 1,
  libraryResultFilter: new Set(),
  practiceStartResultFilter: new Set(),
  practiceResultFilter: null,
  practiceRandomStart: storedRandomStart(),
  practiceOrder: null,
  practiceShufflePending: false,
  refreshRequestId: 0,
  localFilter: null,
  resultContext: null,
  questionAttemptHistoryRequestId: 0,
  imageLightboxTrigger: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const SELF_MARKS = {
  ok: { label: "○", text: "できた", className: "ok" },
  warn: { label: "△", text: "要確認", className: "warn" },
  wrong: { label: "×", text: "できない", className: "wrong" },
};

const RESULT_FILTER_ORDER = ["ok", "warn", "wrong", "untried"];

const KNOWN_EXAMS = ["放射線診断専門医認定試験", "核医学専門医試験", "放射線治療専門医認定試験"];

const EXAM_LABELS = {
  放射線診断専門医認定試験: "診断専門医",
  核医学専門医試験: "核医学専門医",
  放射線治療専門医認定試験: "治療専門医",
};

const CATEGORY_ORDERS = {
  放射線診断専門医認定試験: [
    "画像診断学総論",
    "中枢神経",
    "頭頚部",
    "脊椎・脊髄",
    "骨軟部",
    "呼吸器・縦隔",
    "心血管・脈管",
    "乳房",
    "消化器",
    "泌尿器・生殖器",
    "IVR",
    "核医学",
  ],
  放射線治療専門医認定試験: [
    "放射線治療総合",
    "基礎・物理",
    "生物・薬剤",
    "治療計画・照射技術",
    "安全管理・QA",
    "中枢神経・頭頸部",
    "胸部・乳腺",
    "消化器",
    "泌尿器・婦人科",
    "血液・小児・骨軟部",
    "緩和・良性疾患",
  ],
  核医学専門医試験: [
    "医療安全・関連法規・倫理",
    "放射性医薬品の基礎知識",
    "撮像機器・撮像法",
    "呼吸器・内分泌",
    "消化器・泌尿器",
    "心臓",
    "腫瘍",
    "骨・関節・軟部組織・炎症・血液・リンパ",
    "中枢神経",
    "核医学治療",
  ],
};

const fields = {
  statQuestions: $("#statQuestions"),
  statAttempts: $("#statAttempts"),
  statRate: $("#statRate"),
  examTabs: $("#examTabs"),
  currentUserDisplay: $("#currentUserDisplay"),
  userForm: $("#userForm"),
  userNameInput: $("#userNameInput"),
  userSourceLabel: $("#userSourceLabel"),
  usersTab: $("#usersTab"),
  userAdminForm: $("#userAdminForm"),
  newUserNameInput: $("#newUserNameInput"),
  userTable: $("#userTable"),
  filterYear: $("#filterYear"),
  filterCategory: $("#filterCategory"),
  filterKeyword: $("#filterKeyword"),
  filterPanel: $("#filterPanel"),
  filterSummaryText: $("#filterSummaryText"),
  practiceResultFilter: $("#practiceResultFilter"),
  practiceRandomToggle: $("#practiceRandomToggle"),
  startAllRandom: $("#startAllRandom"),
  studyMap: $("#studyMap"),
  studyList: $("#studyList"),
  practiceSession: $("#practiceSession"),
  backToStudyMap: $("#backToStudyMap"),
  jumpForm: $("#jumpForm"),
  jumpQuestionNumber: $("#jumpQuestionNumber"),
  navButtons: $(".nav-buttons"),
  prevQuestion: $("#prevQuestion"),
  nextQuestion: $("#nextQuestion"),
  questionArea: $("#questionArea"),
  emptyPractice: $("#emptyPractice"),
  questionMeta: $("#questionMeta"),
  questionText: $("#questionText"),
  questionSourceLinks: $("#questionSourceLinks"),
  questionImages: $("#questionImages"),
  imageLightbox: $("#imageLightbox"),
  imageLightboxImage: $("#imageLightboxImage"),
  closeImageLightbox: $("#closeImageLightbox"),
  choiceList: $("#choiceList"),
  freeAnswerWrap: $("#freeAnswerWrap"),
  freeAnswer: $("#freeAnswer"),
  resultBox: $("#resultBox"),
  questionAttemptHistory: $("#questionAttemptHistory"),
  noteForm: $("#noteForm"),
  questionNote: $("#questionNote"),
  saveNote: $("#saveNote"),
  noteStatus: $("#noteStatus"),
  practiceCategoryEditor: $("#practiceCategoryEditor"),
  practiceCategorySelect: $("#practiceCategorySelect"),
  savePracticeCategory: $("#savePracticeCategory"),
  questionTable: $("#questionTable"),
  historyTable: $("#historyTable"),
  clearHistory: $("#clearHistory"),
  libraryCount: $("#libraryCount"),
  libraryFilter: $("#libraryFilter"),
  libraryPagination: $("#libraryPagination"),
  libraryPrevPage: $("#libraryPrevPage"),
  libraryNextPage: $("#libraryNextPage"),
  libraryPageStatus: $("#libraryPageStatus"),
  toast: $("#toast"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortText(value, length = 80) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > length ? `${text.slice(0, length)}...` : text;
}

function questionNumber(question) {
  const match = String(question?.question || "").match(/問\s*(\d{1,3})/);
  return match ? Number(match[1]) : null;
}

function questionAttempted(question) {
  return Number(question?.attempts_count || 0) > 0;
}

function questionSelfMark(question) {
  if (!questionAttempted(question)) return "untried";
  return SELF_MARKS[question?.last_self_mark] ? question.last_self_mark : "warn";
}

function questionResultBadge(question) {
  const mark = questionSelfMark(question);
  if (mark === "untried") {
    return `<span class="result-mark pending" title="未演習">未</span>`;
  }
  const meta = SELF_MARKS[mark];
  return `<span class="result-mark ${meta.className}" title="${meta.text}">${meta.label}</span>`;
}

function resultFilterLabel(mark) {
  if (mark === "untried") return "未演習";
  const meta = SELF_MARKS[mark];
  return meta ? `${meta.label} ${meta.text}` : "";
}

function resultFilterLabels(resultFilter) {
  if (!resultFilter?.size) return [];
  return RESULT_FILTER_ORDER.filter((mark) => resultFilter.has(mark))
    .map(resultFilterLabel)
    .filter(Boolean);
}

function copyResultFilter(resultFilter) {
  return resultFilter?.size ? new Set(resultFilter) : null;
}

function shuffledPracticeOrder(questions) {
  const ids = questions.map((question) => question.id);
  for (let i = ids.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [ids[i], ids[j]] = [ids[j], ids[i]];
  }
  return new Map(ids.map((id, rank) => [id, rank]));
}

// 解答登録のたびに state.questions は組み直されるため、ランダム出題の並びは
// id → 順位のマップとして保持し、組み直し後もこのマップで並べ直す。
function applyPracticeOrder(questions) {
  const order = state.practiceOrder;
  if (!order) return questions;
  return [...questions].sort((a, b) => (order.get(a.id) ?? Infinity) - (order.get(b.id) ?? Infinity));
}

function applyResultFilter(questions, resultFilter) {
  const selected = resultFilter;
  if (!selected || !selected.size) return questions;
  return questions.filter((question) => selected.has(questionSelfMark(question)));
}

function applyLocalFilter(questions, filter) {
  if (!filter) return questions;
  return questions.filter((question) => {
    if (filter.hasImages && !(question.images || []).length) return false;
    if (filter.unattempted && questionAttempted(question)) return false;
    if (filter.withoutAnswer && String(question.answer || "").trim()) return false;
    return true;
  });
}

function baseQuestionList() {
  return state.localFilter ? applyLocalFilter(state.allQuestions, state.localFilter) : state.allQuestions;
}

function filteredLibraryQuestions() {
  return applyResultFilter(baseQuestionList(), state.libraryResultFilter);
}

function filteredPracticeQuestions() {
  return applyPracticeOrder(applyResultFilter(baseQuestionList(), state.practiceResultFilter));
}

function toast(message) {
  fields.toast.textContent = message;
  fields.toast.classList.remove("hidden");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => fields.toast.classList.add("hidden"), 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "処理に失敗しました。");
  }
  return data;
}

function selectedFilters() {
  const params = new URLSearchParams();
  params.set("user", state.currentUser);
  if (state.selectedExam) params.set("exam", state.selectedExam);
  if (fields.filterYear.value) params.set("year", fields.filterYear.value);
  if (fields.filterCategory.value) params.set("category", fields.filterCategory.value);
  if (fields.filterKeyword.value.trim()) params.set("q", fields.filterKeyword.value.trim());
  return params.toString();
}

function queryFor(params) {
  const query = params.toString();
  return query ? `?${query}` : "";
}

function userScopedParams(initial = {}) {
  const params = new URLSearchParams(initial);
  params.set("user", state.currentUser);
  return params;
}

function hasActiveQuestionFilter() {
  return Boolean(
    fields.filterYear.value ||
      fields.filterCategory.value ||
      fields.filterKeyword.value.trim() ||
      state.localFilter,
  );
}

function clearQuestionLists() {
  state.allQuestions = [];
  state.studyQuestions = [];
  state.questions = [];
  state.questionsLoaded = false;
  state.practiceResultFilter = null;
  state.practiceOrder = null;
  state.practiceShufflePending = false;
}

async function refreshSession() {
  const session = await api("/api/session");
  state.session = session;
  if (session.mode === "tailscale" && session.user_name) {
    state.currentUser = normalizeUserName(session.user_name);
  }
  renderUserSwitcher();
  renderUserManagementAccess();
  return session;
}

async function refreshAll({ keepQuestion = false, renderPracticePanel = true, forceLoadQuestions = false } = {}) {
  const requestId = ++state.refreshRequestId;
  const query = selectedFilters();
  const statsParams = userScopedParams();
  if (state.selectedExam) statsParams.set("exam", state.selectedExam);
  const summaryParams = userScopedParams();
  if (state.selectedExam) summaryParams.set("exam", state.selectedExam);
  const shouldLoadQuestions =
    forceLoadQuestions || !state.showStudyMap || state.activeTab === "library" || hasActiveQuestionFilter();
  const [stats, summaryPayload, questionPayload] = await Promise.all([
    api(`/api/stats${queryFor(statsParams)}`),
    api(`/api/study-summary${queryFor(summaryParams)}`),
    shouldLoadQuestions ? api(`/api/questions${query ? `?${query}` : ""}`) : Promise.resolve(null),
    state.activeTab === "history" ? refreshHistory() : Promise.resolve(),
  ]);
  if (requestId !== state.refreshRequestId) return;

  state.stats = stats;
  state.studySummary = summaryPayload;
  if (!state.selectedExam && stats.exams?.length) {
    state.selectedExam = stats.exams.includes(KNOWN_EXAMS[0]) ? KNOWN_EXAMS[0] : stats.exams[0];
  }
  renderUserSwitcher();
  if (questionPayload) {
    state.allQuestions = questionPayload.questions || [];
    state.studyQuestions = state.allQuestions;
    state.questions = filteredPracticeQuestions();
    if (state.practiceShufflePending) {
      state.practiceOrder = shuffledPracticeOrder(state.questions);
      state.practiceShufflePending = false;
      state.questions = filteredPracticeQuestions();
    }
    state.questionsLoaded = true;
  } else {
    clearQuestionLists();
  }
  renderStats();
  renderExamTabs();
  renderFilters();
  renderStudyMap();
  renderQuestionTable();

  if (!renderPracticePanel) {
    return;
  }

  if (state.showStudyMap && state.activeTab === "practice") {
    showStudyMap();
    return;
  }

  if (!keepQuestion || !state.currentQuestion) {
    setCurrentQuestionByIndex(0);
  } else {
    const freshIndex = state.questions.findIndex((item) => item.id === state.currentQuestion.id);
    if (freshIndex >= 0) {
      state.currentIndex = freshIndex;
      state.currentQuestion = state.questions[freshIndex];
    } else {
      state.currentIndex = state.questions.length ? 0 : -1;
      state.currentQuestion = state.questions[0] || null;
    }
    renderPractice();
  }
}

function renderUserSwitcher() {
  if (fields.currentUserDisplay) {
    fields.currentUserDisplay.textContent = `ユーザー: ${state.currentUser}`;
  }
  if (fields.userNameInput && fields.userNameInput.value !== state.currentUser) {
    fields.userNameInput.value = state.currentUser;
  }
  const locked = state.session?.can_switch_user === false;
  if (fields.userNameInput) {
    fields.userNameInput.disabled = locked;
  }
  const button = fields.userForm?.querySelector("button[type='submit']");
  if (button) {
    button.disabled = locked;
    button.textContent = locked ? "固定" : "切替";
  }
  if (fields.userSourceLabel) {
    fields.userSourceLabel.textContent = locked ? "Tailscaleログイン" : "";
  }
}

function renderUserManagementAccess() {
  const canManage = state.session?.can_manage_users === true;
  fields.usersTab?.classList.toggle("hidden", !canManage);
  if (!canManage && state.activeTab === "users") {
    activateTab("practice");
  }
}

function switchUser(value) {
  if (state.session?.can_switch_user === false) {
    renderUserSwitcher();
    return;
  }
  const nextUser = normalizeUserName(value);
  if (fields.userNameInput) fields.userNameInput.value = nextUser;
  if (nextUser === state.currentUser) return;

  state.currentUser = nextUser;
  state.resultContext = null;
  state.practiceResultFilter = null;
  state.showStudyMap = true;
  try {
    window.localStorage.setItem(USER_STORAGE_KEY, nextUser);
  } catch {
    // 履歴自体はサーバー側に残るので、端末保存に失敗しても演習は継続できます。
  }
  toast(`${nextUser} の履歴に切り替えました。`);
  refreshAll({ keepQuestion: false }).catch((error) => toast(error.message));
}

function renderStats() {
  if (fields.statQuestions) fields.statQuestions.textContent = state.stats?.questions ?? 0;
  if (fields.statAttempts) fields.statAttempts.textContent = state.stats?.attempts ?? 0;
  if (fields.statRate) fields.statRate.textContent = `${state.stats?.rate ?? 0}%`;
}

function examLabel(exam) {
  return EXAM_LABELS[exam] || exam || "未分類";
}

function availableExams() {
  const exams = [...KNOWN_EXAMS, ...(state.stats?.exams || [])];
  return [...new Set(exams.filter(Boolean))];
}

function renderExamTabs() {
  if (!fields.examTabs) return;
  const exams = availableExams();
  fields.examTabs.innerHTML = exams
    .map((exam) => {
      const active = exam === state.selectedExam ? " active" : "";
      return `<button class="exam-tab${active}" type="button" data-exam="${escapeHtml(exam)}">${escapeHtml(examLabel(exam))}</button>`;
    })
    .join("");
}

function setSelectOptions(select, values, current, label) {
  const escaped = values.map((value) => {
    const selected = value === current ? " selected" : "";
    return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(value)}</option>`;
  });
  select.innerHTML = `<option value="">${label}</option>${escaped.join("")}`;
}

function sortedCategories(values, exam = state.selectedExam) {
  return [...(values || [])].sort(
    (a, b) => categoryOrder(a, exam) - categoryOrder(b, exam) || String(a).localeCompare(String(b), "ja"),
  );
}

function renderFilters() {
  setSelectOptions(fields.filterYear, state.stats?.years || [], fields.filterYear.value, "すべて");
  setSelectOptions(fields.filterCategory, sortedCategories(state.stats?.categories), fields.filterCategory.value, "すべて");
  renderFilterSummary();
}

function renderFilterSummary() {
  if (!fields.filterSummaryText) return;
  const parts = [];
  if (fields.filterYear.value) parts.push(fields.filterYear.value);
  if (fields.filterCategory.value) parts.push(fields.filterCategory.value);
  if (fields.filterKeyword.value.trim()) parts.push(`検索: ${fields.filterKeyword.value.trim()}`);
  if (state.localFilter?.hasImages) parts.push("画像あり");
  if (state.localFilter?.unattempted) parts.push("未演習");
  if (state.localFilter?.withoutAnswer) parts.push("解答未登録");
  if (state.activeTab === "practice" && !state.showStudyMap) {
    if (state.practiceOrder || state.practiceShufflePending) parts.push("ランダム出題");
    const resultLabels = resultFilterLabels(state.practiceResultFilter);
    if (resultLabels.length) parts.push(`開始条件: ${resultLabels.join(", ")}`);
  }
  fields.filterSummaryText.textContent = parts.length ? parts.join(" / ") : "すべて";
}

function isCompactFilterViewport() {
  return window.matchMedia?.(COMPACT_FILTER_MEDIA).matches ?? false;
}

function updateFilterPanelOpen() {
  if (!fields.filterPanel) return;
  const collapse = state.activeTab === "practice" && !state.showStudyMap && isCompactFilterViewport();
  fields.filterPanel.open = !collapse;
}

function categoryOrder(category, exam = state.selectedExam) {
  const order = CATEGORY_ORDERS[exam] || [];
  const index = order.indexOf(category);
  return index >= 0 ? index : order.length;
}

function summarizeQuestions(questions) {
  const total = questions.length;
  const counts = {
    ok: 0,
    warn: 0,
    wrong: 0,
    untried: 0,
  };
  questions.forEach((question) => {
    counts[questionSelfMark(question)] += 1;
  });
  const attempted = counts.ok + counts.warn + counts.wrong;
  return {
    total,
    attempted,
    ok: counts.ok,
    warn: counts.warn,
    wrong: counts.wrong,
    untried: counts.untried,
    remaining: counts.untried,
    percent: total ? Math.round((attempted * 100) / total) : 0,
  };
}

function renderStudyProgress(row) {
  const segments = [
    ["ok", row.ok],
    ["warn", row.warn],
    ["wrong", row.wrong],
    ["untried", row.untried],
  ];
  return segments
    .filter(([, count]) => count > 0)
    .map(([name, count]) => {
      const width = row.total ? (count * 100) / row.total : 0;
      return `<span class="study-progress-${name}" data-width="${width}"></span>`;
    })
    .join("");
}

function studyRowsFromSummary(kind) {
  const rows = Array.isArray(state.studySummary?.[kind]) ? state.studySummary[kind] : [];
  return rows.map((row) => {
    const label = String(row.label || "");
    return {
      label: kind === "year" ? `${label}年` : label,
      filter: kind === "year" ? { year: label } : { category: label },
      total: Number(row.total || 0),
      attempted: Number(row.attempted || 0),
      ok: Number(row.ok || 0),
      warn: Number(row.warn || 0),
      wrong: Number(row.wrong || 0),
      untried: Number(row.untried || 0),
      remaining: Number(row.remaining || row.untried || 0),
      percent: Number(row.percent || 0),
    };
  });
}

function buildStudyRows() {
  if (state.studySummary) {
    if (state.studyMode === "year") {
      const rows = studyRowsFromSummary("year").sort((a, b) =>
        String(b.filter.year).localeCompare(String(a.filter.year)),
      );
      return [{ title: "年度別", note: "", rows }];
    }

    const rows = studyRowsFromSummary("category").sort(
      (a, b) =>
        categoryOrder(a.filter.category) - categoryOrder(b.filter.category) || a.label.localeCompare(b.label, "ja"),
    );
    return [{ title: "分野別", note: "", rows }];
  }

  const source = state.studyQuestions || [];
  if (state.studyMode === "year") {
    const years = [...new Set(source.map((question) => question.year).filter(Boolean))].sort((a, b) =>
      String(b).localeCompare(String(a)),
    );
    const rows = years.map((year) => {
      const questions = source.filter((question) => question.year === year);
      return {
        label: `${year}年`,
        filter: { year },
        ...summarizeQuestions(questions),
      };
    });
    return [{ title: "年度別", note: "", rows }];
  }

  const categories = sortedCategories([...new Set(source.map((question) => question.category).filter(Boolean))]);
  const rows = categories.map((category) => {
    const questions = source.filter((question) => question.category === category);
    return {
      label: category,
      filter: { category },
      ...summarizeQuestions(questions),
    };
  });
  return [{ title: "分野別", note: "", rows }];
}

function renderStudyMap() {
  if (!fields.studyList) return;
  if (fields.startAllRandom) {
    fields.startAllRandom.textContent = `全問題をランダムに解く（${Number(state.stats?.questions || 0)}問）`;
  }
  const sections = buildStudyRows();
  state.studyItems = [];
  fields.studyList.innerHTML = sections
    .map((section) => {
      const rows = section.rows
        .map((row) => {
          const itemIndex = state.studyItems.push(row) - 1;
          const progressLabel = `○${row.ok} △${row.warn} ×${row.wrong} 未${row.untried}`;
          return `
            <div class="study-row">
              <button class="study-row-main" type="button" data-study-index="${itemIndex}">
                <span class="study-title">${escapeHtml(row.label)} <small>(${row.total})</small></span>
                <span class="study-progress" aria-label="${progressLabel}">
                  ${renderStudyProgress(row)}
                </span>
                <span class="study-status">${progressLabel}</span>
              </button>
            </div>
          `;
        })
        .join("");
      const sectionHead = section.title
        ? `
          <div class="study-section-head">
            <h3>${escapeHtml(section.title)}</h3>
            ${section.note ? `<span>${escapeHtml(section.note)}</span>` : ""}
          </div>
        `
        : "";
      return `
        <section class="study-section">
          ${sectionHead}
          <div class="study-rows">${rows}</div>
        </section>
      `;
    })
    .join("");

  // Apply progress-bar widths via the DOM API so the strict Content-Security-Policy
  // (default-src 'self', no inline styles) does not block them.
  fields.studyList.querySelectorAll(".study-progress span[data-width]").forEach((span) => {
    span.style.width = `${span.dataset.width}%`;
  });

  $$(".study-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.studyMode === state.studyMode);
  });
  renderPracticeResultFilter();
}

function renderPracticeResultFilter() {
  if (fields.practiceRandomToggle) {
    fields.practiceRandomToggle.checked = state.practiceRandomStart;
  }
  if (!fields.practiceResultFilter) return;
  $$("[data-practice-result-filter]").forEach((input) => {
    input.checked = state.practiceStartResultFilter.has(input.dataset.practiceResultFilter);
  });
}

function showStudyMap() {
  state.showStudyMap = true;
  state.currentQuestion = null;
  state.currentIndex = -1;
  fields.studyMap.classList.remove("hidden");
  fields.practiceSession.classList.add("hidden");
  fields.jumpForm.classList.add("hidden");
  fields.navButtons.classList.add("hidden");
  fields.backToStudyMap.classList.add("hidden");
  fields.filterPanel.open = true;
  document.body.classList.toggle("study-map-active", state.activeTab === "practice");
  document.body.classList.remove("practice-session-active");
}

function clearStudyFilters({ keepExam = true } = {}) {
  if (!keepExam) state.selectedExam = "";
  fields.filterYear.value = "";
  fields.filterCategory.value = "";
  fields.filterKeyword.value = "";
  state.libraryPage = 1;
  state.localFilter = null;
  state.practiceResultFilter = null;
  state.practiceOrder = null;
  state.practiceShufflePending = false;
  renderFilterSummary();
}

function showPracticeSession() {
  state.showStudyMap = false;
  fields.studyMap.classList.add("hidden");
  fields.practiceSession.classList.remove("hidden");
  fields.jumpForm.classList.remove("hidden");
  fields.navButtons.classList.remove("hidden");
  fields.backToStudyMap.classList.remove("hidden");
  updateFilterPanelOpen();
  document.body.classList.remove("study-map-active");
  document.body.classList.toggle("practice-session-active", state.activeTab === "practice");
}

function startPractice(filter = {}, { forceRandom = false } = {}) {
  state.localFilter = filter.localFilter || null;
  state.practiceResultFilter = copyResultFilter(state.practiceStartResultFilter);
  state.practiceOrder = null;
  state.practiceShufflePending = forceRandom || state.practiceRandomStart;
  fields.filterYear.value = filter.year || "";
  fields.filterCategory.value = filter.category || "";
  fields.filterKeyword.value = filter.q || "";
  state.libraryPage = 1;
  state.showStudyMap = false;
  renderFilterSummary();
  refreshAll({ keepQuestion: false }).catch((error) => toast(error.message));
}

function startStudyItem(index) {
  const item = state.studyItems[index];
  if (!item) return;
  startPractice(item.filter || {});
}

function switchExam(exam) {
  if (!exam || exam === state.selectedExam) return;
  state.selectedExam = exam;
  clearStudyFilters();
  clearQuestionLists();
  state.currentQuestion = null;
  state.currentIndex = -1;
  state.resultContext = null;
  state.showStudyMap = true;
  refreshAll({ keepQuestion: false }).catch((error) => toast(error.message));
}

function resetScroll() {
  window.scrollTo(0, 0);
}

function setCurrentQuestionByIndex(index) {
  if (!state.questions.length) {
    showPracticeSession();
    state.currentQuestion = null;
    state.currentIndex = -1;
    renderPractice();
    resetScroll();
    return;
  }

  state.currentIndex = (index + state.questions.length) % state.questions.length;
  state.currentQuestion = state.questions[state.currentIndex];
  showPracticeSession();
  renderPractice();
  resetScroll();
}

function pickNextQuestion() {
  setCurrentQuestionByIndex(state.currentIndex + 1);
}

function pickPreviousQuestion() {
  setCurrentQuestionByIndex(state.currentIndex - 1);
}

function pickQuestionAfterRefresh(previousQuestionId, previousIndex) {
  if (!state.questions.length) {
    setCurrentQuestionByIndex(0);
    return;
  }

  const freshIndex = state.questions.findIndex((question) => question.id === previousQuestionId);
  if (freshIndex >= 0) {
    setCurrentQuestionByIndex(freshIndex + 1);
    return;
  }

  const nextIndex = Math.min(Math.max(0, previousIndex), state.questions.length - 1);
  setCurrentQuestionByIndex(nextIndex);
}

function jumpToQuestion(event) {
  event.preventDefault();
  const number = Number(fields.jumpQuestionNumber.value);
  if (!Number.isInteger(number) || number <= 0) {
    toast("問題番号を入力してください。");
    return;
  }

  const index = state.questions.findIndex((question) => questionNumber(question) === number);
  if (index < 0) {
    toast(`問${number}は現在の条件内にありません。`);
    return;
  }

  setCurrentQuestionByIndex(index);
}

function renderPractice() {
  closeImageLightbox({ restoreFocus: false });
  const question = state.currentQuestion;
  state.resultContext = null;
  state.questionAttemptHistoryRequestId += 1;
  fields.resultBox.className = "result-box hidden";
  fields.resultBox.textContent = "";
  fields.questionAttemptHistory.classList.add("hidden");
  fields.questionAttemptHistory.removeAttribute("aria-busy");
  fields.questionAttemptHistory.textContent = "";
  fields.choiceList.innerHTML = "";
  fields.questionSourceLinks.innerHTML = "";
  fields.freeAnswer.value = "";
  fields.questionNote.value = question?.user_note || "";
  fields.noteStatus.textContent = "";
  setAnswerControlsDisabled(false);

  if (!question) {
    fields.emptyPractice.classList.remove("hidden");
    fields.questionArea.classList.add("hidden");
    fields.jumpQuestionNumber.value = "";
    fields.jumpQuestionNumber.disabled = true;
    fields.prevQuestion.disabled = true;
    fields.nextQuestion.disabled = true;
    if (fields.practiceCategoryEditor) fields.practiceCategoryEditor.classList.add("hidden");
    return;
  }

  const number = questionNumber(question);
  fields.jumpQuestionNumber.disabled = false;
  fields.prevQuestion.disabled = false;
  fields.nextQuestion.disabled = false;
  fields.jumpQuestionNumber.value = number || "";
  fields.emptyPractice.classList.add("hidden");
  fields.questionArea.classList.remove("hidden");
  fields.questionMeta.innerHTML = [question.year, question.category]
    .filter(Boolean)
    .map((value) => `<span>${escapeHtml(value)}</span>`)
    .join("");
  renderPracticeCategoryEditor(question);
  fields.questionText.textContent = question.question;
  fields.questionSourceLinks.innerHTML = question.source_pdf?.url
    ? `
      <a class="source-pdf-link" href="${escapeHtml(question.source_pdf.url)}" target="_blank" rel="noopener">
        元PDFを確認
        <span>${escapeHtml(question.source_pdf.label || "")}</span>
      </a>
    `
    : "";
  fields.questionImages.innerHTML = (question.images || [])
    .map((src, index) => `
      <figure>
        <button
          class="question-image-trigger"
          type="button"
          aria-label="問題画像 ${index + 1} を拡大表示"
          aria-haspopup="dialog"
        >
          <img src="${escapeHtml(src)}" alt="問題画像 ${index + 1}" loading="lazy">
        </button>
      </figure>
    `)
    .join("");

  if (question.choices?.length) {
    const inputType = expectsMultiple(question) ? "checkbox" : "radio";
    fields.freeAnswerWrap.classList.add("hidden");
    fields.choiceList.innerHTML = question.choices
      .map(
        (choice, index) => `
          <label class="choice">
            <input type="${inputType}" name="choiceAnswer" value="${escapeHtml(choiceAnswerValue(choice, index))}">
            <span>${escapeHtml(choice)}</span>
          </label>
        `,
      )
      .join("");
  } else {
    fields.freeAnswerWrap.classList.remove("hidden");
  }
}

function categoryOptionsForPractice(question) {
  const source = state.studyQuestions?.length ? state.studyQuestions : state.allQuestions;
  const categories = source.length
    ? source
        .filter((item) => !question?.exam || item.exam === question.exam)
        .map((item) => item.category)
        .filter(Boolean)
    : [...(state.stats?.categories || [])];
  if (question?.category) categories.push(question.category);
  return sortedCategories([...new Set(categories)], question?.exam);
}

function renderPracticeCategoryEditor(question) {
  if (!fields.practiceCategoryEditor || !fields.practiceCategorySelect) return;
  if (state.session?.can_edit_questions !== true) {
    fields.practiceCategoryEditor.classList.add("hidden");
    return;
  }
  const categories = categoryOptionsForPractice(question);
  if (!categories.length) {
    fields.practiceCategoryEditor.classList.add("hidden");
    return;
  }
  fields.practiceCategoryEditor.classList.remove("hidden");
  fields.practiceCategorySelect.innerHTML = categories
    .map((category) => {
      const selected = category === question.category ? " selected" : "";
      return `<option value="${escapeHtml(category)}"${selected}>${escapeHtml(category)}</option>`;
    })
    .join("");
}

function replaceQuestionInList(list, updatedQuestion) {
  const index = list.findIndex((item) => item.id === updatedQuestion.id);
  if (index >= 0) list[index] = updatedQuestion;
}

async function savePracticeCategory() {
  if (state.session?.can_edit_questions !== true) {
    toast("分野修正は管理者のみ使用できます。");
    return;
  }
  const question = state.currentQuestion;
  if (!question || !fields.practiceCategorySelect) return;
  const category = fields.practiceCategorySelect.value;
  if (!category || category === question.category) {
    toast("分野は変更されていません。");
    return;
  }

  try {
    const result = await api(`/api/questions/${question.id}`, {
      method: "PUT",
      body: JSON.stringify({ category }),
    });
    state.currentQuestion = result.question;
    replaceQuestionInList(state.questions, result.question);
    replaceQuestionInList(state.allQuestions, result.question);
    replaceQuestionInList(state.studyQuestions, result.question);
    renderPractice();
    renderStudyMap();
    renderQuestionTable();
    toast("分野を更新しました。");
  } catch (error) {
    toast(error.message);
  }
}

async function saveQuestionNote(event) {
  event.preventDefault();
  const question = state.currentQuestion;
  if (!question) return;

  const note = fields.questionNote.value.trim();
  fields.saveNote.disabled = true;
  fields.noteStatus.textContent = "保存中";

  try {
    const result = await api(`/api/notes/${question.id}`, {
      method: "POST",
      body: JSON.stringify({ note, user_name: state.currentUser }),
    });
    const updatedQuestion = {
      ...question,
      user_note: result.note || "",
      user_note_updated_at: result.updated_at || null,
    };
    state.currentQuestion = updatedQuestion;
    replaceQuestionInList(state.questions, updatedQuestion);
    replaceQuestionInList(state.allQuestions, updatedQuestion);
    replaceQuestionInList(state.studyQuestions, updatedQuestion);
    fields.noteStatus.textContent = result.note ? "保存済み" : "削除済み";
  } catch (error) {
    fields.noteStatus.textContent = "";
    toast(error.message);
  } finally {
    fields.saveNote.disabled = false;
  }
}

function expectsMultiple(question) {
  if (answerLetters(question?.answer).length > 1) return true;
  const text = question?.question || "";
  return /(?:[２2二]\s*つ|[２2二]\s*個|すべて)\s*選べ/.test(text);
}

function choiceAnswerValue(choice, index) {
  const match = String(choice || "").trim().match(/^([a-e])\s*[\.)．、，,：:]/i);
  return match ? match[1].toLowerCase() : String.fromCharCode(97 + index);
}

function currentAnswer() {
  const question = state.currentQuestion;
  if (!question) return "";
  if (question.choices?.length) {
    return $$("input[name='choiceAnswer']:checked")
      .map((item) => item.value)
      .join("; ");
  }
  return fields.freeAnswer.value.trim();
}

function setAnswerControlsDisabled(disabled) {
  $$("#choiceList input").forEach((input) => {
    input.disabled = disabled;
  });
  fields.freeAnswer.disabled = disabled;
  const submitButton = $("#answerForm button[type='submit']");
  if (submitButton) submitButton.disabled = disabled;
}

function normalizeAnswer(value) {
  return String(value ?? "").trim().toLocaleLowerCase().split(/\s+/).join(" ");
}

function answerLetters(value) {
  const text = normalizeAnswer(value);
  if (!text) return [];
  const direct = /^[a-e](?:\s*[,;/、，]\s*[a-e])*$/.test(text);
  if (direct) return [...new Set(text.match(/[a-e]/g) || [])].sort();

  const labeled = new Set();
  for (const match of text.matchAll(/(?:^|[;\n；])\s*([a-e])\s*[\.)．、，,：:]/g)) {
    labeled.add(match[1]);
  }
  if (labeled.size) return [...labeled].sort();

  const letters = new Set();
  for (const match of text.matchAll(/(^|[^a-z])([a-e])(?=\s*[\.)．、，:：;；]|$)/g)) {
    letters.add(match[2]);
  }
  return [...letters].sort();
}

function sameLetters(left, right) {
  if (left.length !== right.length) return false;
  return left.every((letter, index) => letter === right[index]);
}

function isCorrectAnswer(userAnswer, correctAnswer) {
  const userLetters = answerLetters(userAnswer);
  const correctLetters = answerLetters(correctAnswer);
  if (userLetters.length && correctLetters.length) {
    return sameLetters(userLetters, correctLetters);
  }
  return normalizeAnswer(userAnswer) === normalizeAnswer(correctAnswer);
}

function syncCurrentQuestion() {
  if (!state.currentQuestion) return;
  const freshIndex = state.questions.findIndex((question) => question.id === state.currentQuestion.id);
  if (freshIndex >= 0) {
    state.currentIndex = freshIndex;
    state.currentQuestion = state.questions[freshIndex];
  }
}

function markLabel(mark) {
  return SELF_MARKS[mark]?.label || SELF_MARKS.warn.label;
}

function markClass(mark) {
  return SELF_MARKS[mark]?.className || SELF_MARKS.warn.className;
}

function renderMarkButtons(attemptId, currentMark) {
  return `
    <div class="self-mark-panel" data-attempt-id="${attemptId}">
      <div class="self-mark-title">自己評価</div>
      <div class="self-mark-buttons" aria-label="自己評価">
        ${Object.entries(SELF_MARKS)
          .map(([mark, item]) => {
            const active = mark === currentMark ? " active" : "";
            return `
              <button class="self-mark-button ${item.className}${active}" type="button" data-self-mark="${mark}">
                <strong>${item.label}</strong><span>${item.text}</span>
              </button>
            `;
          })
          .join("")}
      </div>
    </div>
  `;
}

function attemptMarkPresentation(attempt) {
  const selfMark = SELF_MARKS[attempt.self_mark] ? attempt.self_mark : "";
  if (selfMark) {
    return { className: markClass(selfMark), label: markLabel(selfMark) };
  }
  if (attempt.is_correct === 0 || attempt.is_correct === 1) {
    return attempt.is_correct === 1
      ? { className: "ok", label: "正解" }
      : { className: "ng", label: "不正解" };
  }
  return { className: "pending", label: "未採点" };
}

function renderAttemptHistoryRows(attempts = []) {
  return attempts
    .map((attempt) => {
      const parsedDate = new Date(attempt.created_at);
      const date = Number.isNaN(parsedDate.getTime()) ? "日時不明" : parsedDate.toLocaleString("ja-JP");
      const mark = attemptMarkPresentation(attempt);
      return `
        <li class="attempt-history-row">
          <span class="result-mark ${mark.className}">${mark.label}</span>
          <span class="attempt-answer">回答: ${escapeHtml(attempt.user_answer)}</span>
          <time>${escapeHtml(date)}</time>
        </li>
      `;
    })
    .join("");
}

function renderQuestionAttemptHistory(attempts = [], message = "") {
  const title =
    attempts.length === QUESTION_ATTEMPT_HISTORY_LIMIT
      ? `過去の回答記録（直近${QUESTION_ATTEMPT_HISTORY_LIMIT}件）`
      : "過去の回答記録";
  const body = message
    ? `<p class="attempt-history-message">${escapeHtml(message)}</p>`
    : attempts.length
      ? `<ol>${renderAttemptHistoryRows(attempts)}</ol>`
      : `<p class="attempt-history-message">過去の回答はありません。</p>`;
  fields.questionAttemptHistory.innerHTML = `
    <div class="attempt-history-title">${title}</div>
    ${body}
  `;
  fields.questionAttemptHistory.classList.remove("hidden");
}

async function loadQuestionAttemptHistory(questionId) {
  const normalizedId = Number(questionId);
  if (!Number.isInteger(normalizedId) || normalizedId <= 0) return;
  const requestedUser = state.currentUser;
  const requestId = state.questionAttemptHistoryRequestId + 1;
  state.questionAttemptHistoryRequestId = requestId;
  const isCurrentRequest = () =>
    state.questionAttemptHistoryRequestId === requestId &&
    state.currentUser === requestedUser &&
    state.currentQuestion?.id === normalizedId &&
    state.resultContext?.question_id === normalizedId;

  fields.questionAttemptHistory.setAttribute("aria-busy", "true");
  renderQuestionAttemptHistory([], "読み込み中...");
  try {
    const params = userScopedParams({
      question_id: String(normalizedId),
      limit: String(QUESTION_ATTEMPT_HISTORY_LIMIT),
    });
    const payload = await api(`/api/attempts${queryFor(params)}`);
    if (!isCurrentRequest()) return;
    const attempts = Array.isArray(payload.attempts)
      ? payload.attempts.filter(
          (attempt) =>
            Number(attempt.question_id) === normalizedId &&
            typeof attempt.user_name === "string" &&
            normalizeUserName(attempt.user_name) === requestedUser,
        )
      : [];
    fields.questionAttemptHistory.removeAttribute("aria-busy");
    renderQuestionAttemptHistory(attempts);
  } catch (error) {
    if (!isCurrentRequest()) return;
    fields.questionAttemptHistory.removeAttribute("aria-busy");
    renderQuestionAttemptHistory([], "過去の回答記録を読み込めませんでした。");
    toast(error.message);
  }
}

function renderAnswerResult(result) {
  state.resultContext = { ...(state.resultContext || {}), ...result };
  const context = state.resultContext;
  const mark = context.self_mark || "warn";
  const hasCorrectAnswer =
    context.has_correct_answer ?? Boolean(String(context.correct_answer || "").trim());
  const resultClass = context.preview_only
    ? ""
    : context.graded
      ? context.correct
        ? "correct"
        : "wrong"
      : "correct";
  const heading = context.preview_only
    ? "解答・解説"
    : context.graded
      ? context.correct
        ? "正解"
        : "不正解"
      : context.saved
        ? "解答を記録しました"
        : "解答を確認しました";
  const answerBlock = hasCorrectAnswer
    ? `<div>正答: ${escapeHtml(context.correct_answer)}</div>`
    : `<div>この問題は正答未登録です。一覧の編集から正答を追加できます。</div>`;
  const userAnswerBlock = context.user_answer ? `<div>あなたの解答: ${escapeHtml(context.user_answer)}</div>` : "";
  const previewNote = context.preview_only ? `<div>未回答のため、結果は履歴に登録されません。</div>` : "";
  const markButtons = context.preview_only ? "" : renderMarkButtons(context.attempt_id, mark);
  const registerAction = context.preview_only || context.saved
    ? ""
    : `
      <div class="result-actions">
        <button class="primary" type="button" data-register-result>結果を登録して次の問題へ</button>
      </div>
    `;

  fields.resultBox.className = `result-box ${resultClass}`;
  fields.resultBox.innerHTML = `
    <strong>${heading}</strong>
    ${userAnswerBlock}
    ${answerBlock}
    ${previewNote}
    ${context.explanation ? `<div>${escapeHtml(context.explanation).replaceAll("\n", "<br>")}</div>` : ""}
    ${markButtons}
    ${registerAction}
  `;
}

async function submitAnswer(event) {
  event.preventDefault();
  if (!state.currentQuestion) return;

  const userAnswer = currentAnswer();
  const previewOnly = !userAnswer;
  const hasCorrectAnswer = Boolean(String(state.currentQuestion.answer || "").trim());
  const correct = !previewOnly && hasCorrectAnswer ? isCorrectAnswer(userAnswer, state.currentQuestion.answer) : null;
  renderAnswerResult({
    attempt_id: null,
    saved: false,
    question_id: state.currentQuestion.id,
    user_answer: userAnswer,
    self_mark: !previewOnly && hasCorrectAnswer ? (correct ? "ok" : "wrong") : "warn",
    preview_only: previewOnly,
    has_correct_answer: hasCorrectAnswer,
    graded: !previewOnly && hasCorrectAnswer,
    correct,
    correct_answer: state.currentQuestion.answer,
    explanation: state.currentQuestion.explanation,
    attempts: [],
  });
  setAnswerControlsDisabled(true);
  void loadQuestionAttemptHistory(state.currentQuestion.id);
}

// 解答登録のたびに全データを再取得すると、不安定な回線(モバイル+Tailscale)では
// 1問ごとに数秒待たされる。登録内容から結果は決定できるので、サーバーへは
// POST/PUT 1回だけ送り、集計(問題リスト・演習マップ・統計)はローカルで更新する。
function questionById(questionId) {
  return (
    state.allQuestions.find((item) => item.id === questionId) ||
    (state.currentQuestion?.id === questionId ? state.currentQuestion : null)
  );
}

function updateSummaryRows(kind, label, prevMark, nextMark) {
  const rows = Array.isArray(state.studySummary?.[kind]) ? state.studySummary[kind] : [];
  const row = rows.find((item) => String(item.label ?? "") === String(label ?? ""));
  if (!row) return;
  if (prevMark !== "untried") row[prevMark] = Math.max(0, Number(row[prevMark] || 0) - 1);
  row[nextMark] = Number(row[nextMark] || 0) + 1;
  row.attempted = row.ok + row.warn + row.wrong;
  row.untried = Math.max(0, row.total - row.attempted);
  row.remaining = row.untried;
  row.percent = row.total ? Math.round((row.attempted * 100) / row.total) : 0;
}

function applyMarkTransition(question, prevMark, nextMark) {
  if (!state.studySummary || prevMark === nextMark) return;
  updateSummaryRows("year", question.year, prevMark, nextMark);
  updateSummaryRows("category", question.category, prevMark, nextMark);
}

function refreshQuestionViews() {
  state.questions = filteredPracticeQuestions();
  renderStats();
  renderStudyMap();
  renderQuestionTable();
}

function recordAttemptLocally(questionId, { selfMark, graded, correct }) {
  const question = questionById(questionId);
  if (!question) return;
  const prevMark = questionSelfMark(question);
  question.attempts_count = Number(question.attempts_count || 0) + 1;
  question.last_self_mark = selfMark;
  question.last_attempt_at = new Date().toISOString();
  if (graded) {
    question.graded_count = Number(question.graded_count || 0) + 1;
    if (correct) question.correct_count = Number(question.correct_count || 0) + 1;
  }
  if (state.stats) {
    state.stats.attempts = Number(state.stats.attempts || 0) + 1;
    if (prevMark === "untried") {
      state.stats.attempted_questions = Number(state.stats.attempted_questions || 0) + 1;
    }
    if (graded) {
      state.stats.graded_attempts = Number(state.stats.graded_attempts || 0) + 1;
      if (correct) state.stats.correct = Number(state.stats.correct || 0) + 1;
      state.stats.rate = state.stats.graded_attempts
        ? Math.round((state.stats.correct * 1000) / state.stats.graded_attempts) / 10
        : 0;
    }
  }
  applyMarkTransition(question, prevMark, selfMark);
  refreshQuestionViews();
}

// 更新対象は直前に登録した最新の解答に限られるため、last_self_mark を直接置き換えられる。
function applySelfMarkLocally(questionId, selfMark) {
  const question = questionById(questionId);
  if (!question) return;
  const prevMark = questionSelfMark(question);
  question.last_self_mark = selfMark;
  applyMarkTransition(question, prevMark, selfMark);
  refreshQuestionViews();
  syncCurrentQuestion();
}

async function registerPendingResult() {
  const context = state.resultContext;
  if (!context || context.preview_only || context.saved || context.registering) return;
  if (!context.question_id || !context.user_answer) {
    toast("先に判定してください。");
    return;
  }

  const previousQuestionId = state.currentQuestion?.id || context.question_id;
  const previousIndex = state.currentIndex;
  state.resultContext = { ...context, registering: true };
  try {
    const result = await api("/api/attempts", {
      method: "POST",
      body: JSON.stringify({
        question_id: context.question_id,
        user_name: state.currentUser,
        user_answer: context.user_answer,
        self_mark: context.self_mark || "warn",
      }),
    });
    recordAttemptLocally(context.question_id, {
      selfMark: result.self_mark || context.self_mark || "warn",
      graded: Boolean(result.graded),
      correct: result.correct === true,
    });
    toast("結果を登録しました。");
    pickQuestionAfterRefresh(previousQuestionId, previousIndex);
  } catch (error) {
    state.resultContext = { ...context, registering: false };
    toast(error.message);
  }
}

async function updateSelfMark(event) {
  const button = event.target.closest("[data-self-mark]");
  if (!button || !state.resultContext) return;
  const mark = button.dataset.selfMark;
  if (!state.resultContext.attempt_id) {
    renderAnswerResult({ self_mark: mark });
    return;
  }

  try {
    const result = await api(`/api/attempts/${state.resultContext.attempt_id}`, {
      method: "PUT",
      body: JSON.stringify({ self_mark: mark, user_name: state.currentUser }),
    });
    renderAnswerResult(result);
    const questionId = state.resultContext?.question_id || state.currentQuestion?.id;
    applySelfMarkLocally(questionId, mark);
  } catch (error) {
    toast(error.message);
  }
}

function handleResultBoxClick(event) {
  if (event.target.closest("[data-register-result]")) {
    registerPendingResult();
    return;
  }
  updateSelfMark(event);
}


function renderQuestionTable() {
  if (!state.questionsLoaded) {
    fields.libraryCount.textContent = "未読み込み";
    fields.libraryPagination?.classList.add("hidden");
    fields.questionTable.innerHTML = `<tr><td colspan="5">一覧を開くと読み込みます</td></tr>`;
    return;
  }

  const questions = filteredLibraryQuestions();
  const total = questions.length;
  const pageCount = Math.max(1, Math.ceil(total / LIBRARY_PAGE_SIZE));
  state.libraryPage = Math.min(Math.max(1, state.libraryPage), pageCount);
  const start = (state.libraryPage - 1) * LIBRARY_PAGE_SIZE;
  const end = Math.min(start + LIBRARY_PAGE_SIZE, total);
  const visibleQuestions = questions.slice(start, end);

  fields.libraryCount.textContent = total ? `${start + 1}-${end} / ${total}件` : "0件";
  if (fields.libraryPagination) {
    fields.libraryPagination.classList.toggle("hidden", total <= LIBRARY_PAGE_SIZE);
    fields.libraryPageStatus.textContent = `${state.libraryPage} / ${pageCount}`;
    fields.libraryPrevPage.disabled = state.libraryPage <= 1;
    fields.libraryNextPage.disabled = state.libraryPage >= pageCount;
  }

  if (!total) {
    const message = baseQuestionList().length
      ? "選択した結果に一致する問題がありません"
      : "問題がありません";
    fields.questionTable.innerHTML = `<tr><td colspan="5">${message}</td></tr>`;
    return;
  }

  fields.questionTable.innerHTML = visibleQuestions
    .map((question) => {
      const rate = question.answer
        ? question.graded_count
          ? `${question.correct_count}/${question.graded_count}`
          : "-"
        : "正答未登録";
      return `
        <tr>
          <td class="table-year">${escapeHtml(question.year || "-")}</td>
          <td class="table-category" title="${escapeHtml(question.category || "-")}">${escapeHtml(question.category || "-")}</td>
          <td class="question-preview" title="${escapeHtml(question.question)}">${escapeHtml(shortText(question.question))}</td>
          <td class="table-rate">
            <span class="rate-cell">
              ${questionResultBadge(question)}
              <span class="rate-value">${escapeHtml(rate)}</span>
            </span>
          </td>
          <td>
            <div class="table-actions">
              <button class="primary small" type="button" data-practice="${question.id}">演習</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

function setLibraryPage(page) {
  const total = filteredLibraryQuestions().length;
  const pageCount = Math.max(1, Math.ceil(total / LIBRARY_PAGE_SIZE));
  state.libraryPage = Math.min(Math.max(1, page), pageCount);
  renderQuestionTable();
  $("#libraryView .table-wrap")?.scrollIntoView({ block: "start", behavior: "smooth" });
}

async function refreshHistory() {
  const historyParams = userScopedParams({ limit: "80" });
  if (state.selectedExam) historyParams.set("exam", state.selectedExam);
  const payload = await api(`/api/attempts${queryFor(historyParams)}`);
  renderHistory(payload.attempts || []);
}

function renderHistory(attempts) {
  if (!attempts.length) {
    fields.historyTable.innerHTML = `<tr><td colspan="6">履歴がありません</td></tr>`;
    return;
  }

  fields.historyTable.innerHTML = attempts
    .map((attempt) => {
      const date = new Date(attempt.created_at).toLocaleString("ja-JP");
      const graded = attempt.is_correct === 0 || attempt.is_correct === 1;
      const selfMark = attempt.self_mark || "";
      const mark = selfMark ? markLabel(selfMark) : graded ? (attempt.is_correct ? "正解" : "不正解") : "未採点";
      const markClassName = selfMark ? markClass(selfMark) : graded ? (attempt.is_correct ? "ok" : "ng") : "pending";
      return `
        <tr>
          <td class="table-date">${escapeHtml(date)}</td>
          <td><span class="result-mark ${markClassName}">${mark}</span></td>
          <td class="table-category" title="${escapeHtml(attempt.category || "-")}">${escapeHtml(attempt.category || "-")}</td>
          <td class="table-answer">${escapeHtml(attempt.user_answer)}</td>
          <td class="table-answer">${escapeHtml(attempt.answer)}</td>
          <td>
            <button class="danger small" type="button" data-delete-attempt="${attempt.id}">削除</button>
          </td>
        </tr>
      `;
    })
    .join("");
}

async function deleteAllHistory() {
  if (!window.confirm("自分の解答履歴をすべて削除します。よろしいですか？")) return;

  try {
    const result = await api(`/api/attempts${queryFor(userScopedParams())}`, { method: "DELETE" });
    toast(`${Number(result.deleted || 0)}件の履歴を削除しました。`);
    await refreshAll({ keepQuestion: true, renderPracticePanel: false });
    syncCurrentQuestion();
  } catch (error) {
    toast(error.message);
  }
}

async function deleteHistoryAttempt(id) {
  if (!id) return;
  if (!window.confirm("この履歴を削除しますか。")) return;

  try {
    await api(`/api/attempts/${id}${queryFor(userScopedParams())}`, { method: "DELETE" });
    toast("履歴を削除しました。");
    await refreshAll({ keepQuestion: true, renderPracticePanel: false });
    syncCurrentQuestion();
  } catch (error) {
    toast(error.message);
  }
}

async function refreshUsers() {
  if (!state.session?.can_manage_users) {
    state.users = [];
    renderUsers();
    return;
  }
  const payload = await api("/api/users");
  state.users = payload.users || [];
  renderUsers();
}

function renderUsers() {
  if (!fields.userTable) return;
  if (!state.session?.can_manage_users) {
    fields.userTable.innerHTML = `<tr><td colspan="4">管理者として許可されたTailscaleアカウントのみ表示されます</td></tr>`;
    return;
  }
  if (!state.users.length) {
    fields.userTable.innerHTML = `<tr><td colspan="4">ユーザーがありません</td></tr>`;
    return;
  }

  fields.userTable.innerHTML = state.users
    .map((user) => {
      const last = user.last_attempt_at ? new Date(user.last_attempt_at).toLocaleString("ja-JP") : "-";
      const active = user.name === state.currentUser ? " active" : "";
      const cannotDelete = user.name === DEFAULT_USER_NAME || Number(user.attempts_count || 0) > 0;
      const useAction = state.session?.can_switch_user
        ? `<button class="ghost small${active}" type="button" data-use-user="${escapeHtml(user.name)}">使用</button>`
        : active
          ? `<span class="user-source-label">現在</span>`
          : "";
      return `
        <tr>
          <td class="table-user" title="${escapeHtml(user.name)}">${escapeHtml(user.name)}</td>
          <td class="table-rate">${Number(user.attempts_count || 0)}件</td>
          <td class="table-date">${escapeHtml(last)}</td>
          <td>
            <div class="table-actions">
              ${useAction}
              <button class="danger small" type="button" data-delete-user="${user.id}" ${cannotDelete ? "disabled" : ""}>削除</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

async function createManagedUser(event) {
  event.preventDefault();
  if (!state.session?.can_manage_users) {
    toast("ユーザー管理は管理者として許可されたTailscaleアカウントのみ使用できます。");
    return;
  }
  const name = fields.newUserNameInput.value.trim();
  if (!name) {
    toast("ユーザー名を入力してください。");
    return;
  }

  try {
    const payload = await api("/api/users", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    fields.newUserNameInput.value = "";
    state.users = payload.users || [];
    renderUsers();
    toast("ユーザーを追加しました。");
  } catch (error) {
    toast(error.message);
  }
}

async function deleteManagedUser(id) {
  if (!id) return;
  if (!window.confirm("このユーザーを削除しますか。")) return;

  try {
    const payload = await api(`/api/users/${id}`, { method: "DELETE" });
    state.users = payload.users || [];
    renderUsers();
    toast("ユーザーを削除しました。");
  } catch (error) {
    toast(error.message);
  }
}

function handleUserTableClick(event) {
  const useButton = event.target.closest("[data-use-user]");
  if (useButton) {
    switchUser(useButton.dataset.useUser);
    activateTab("practice");
    return;
  }

  const deleteButton = event.target.closest("[data-delete-user]");
  if (deleteButton) {
    deleteManagedUser(Number(deleteButton.dataset.deleteUser));
  }
}

function practiceQuestionFromLibrary(id) {
  const questions = filteredLibraryQuestions();
  const index = questions.findIndex((item) => item.id === id);
  if (index < 0) {
    toast("この問題は現在の一覧に見つかりません。");
    return;
  }
  state.practiceResultFilter = copyResultFilter(state.libraryResultFilter);
  state.practiceOrder = null;
  state.practiceShufflePending = false;
  state.questions = questions;
  state.showStudyMap = false;
  setCurrentQuestionByIndex(index);
  activateTab("practice");
}

function activateTab(name) {
  if (name === "users" && state.session?.can_manage_users !== true) {
    toast("ユーザー管理は管理者として許可されたTailscaleアカウントのみ使用できます。");
    name = "practice";
  }
  state.activeTab = name;
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  $$(".view").forEach((view) => view.classList.remove("active"));
  const view = $(`#${name}View`);
  if (!view) {
    state.activeTab = "practice";
    $("#practiceView").classList.add("active");
    return;
  }
  view.classList.add("active");
  if (name === "practice" && state.showStudyMap) {
    showStudyMap();
  } else {
    document.body.classList.remove("study-map-active");
    document.body.classList.remove("practice-session-active");
    fields.filterPanel.open = true;
  }
  if (name === "practice" && !state.showStudyMap) {
    updateFilterPanelOpen();
    document.body.classList.add("practice-session-active");
  }
  if (name === "library" && !state.questionsLoaded) {
    fields.libraryCount.textContent = "読み込み中";
    fields.questionTable.innerHTML = `<tr><td colspan="5">読み込み中です</td></tr>`;
    refreshAll({ keepQuestion: true, renderPracticePanel: false, forceLoadQuestions: true }).catch((error) =>
      toast(error.message),
    );
  }
  if (name === "history") {
    refreshHistory().catch((error) => toast(error.message));
  }
  if (name === "users") {
    refreshUsers().catch((error) => toast(error.message));
  }
  resetScroll();
}

function openImageLightbox(trigger) {
  const image = trigger?.querySelector("img");
  if (!image || !fields.imageLightbox || !fields.imageLightboxImage) return;

  state.imageLightboxTrigger = trigger;
  fields.imageLightboxImage.src = image.currentSrc || image.src;
  fields.imageLightboxImage.alt = image.alt || "問題画像";

  if (!fields.imageLightbox.open) {
    fields.imageLightbox.showModal();
  }
  document.body.classList.add("image-lightbox-open");
  fields.closeImageLightbox?.focus();
}

function closeImageLightbox({ restoreFocus = true } = {}) {
  if (!fields.imageLightbox || !fields.imageLightboxImage) return;

  const trigger = state.imageLightboxTrigger;
  state.imageLightboxTrigger = null;
  if (fields.imageLightbox.open) {
    fields.imageLightbox.close();
  }
  document.body.classList.remove("image-lightbox-open");
  fields.imageLightboxImage.removeAttribute("src");
  fields.imageLightboxImage.alt = "";

  if (restoreFocus && trigger?.isConnected) {
    trigger.focus({ preventScroll: true });
  }
}

function isImageLightboxBackgroundClick(event) {
  if (event.target === fields.imageLightbox) return true;
  if (event.target !== fields.imageLightboxImage) return false;

  const image = fields.imageLightboxImage;
  if (!image.naturalWidth || !image.naturalHeight) return true;

  const rect = image.getBoundingClientRect();
  const scale = Math.min(rect.width / image.naturalWidth, rect.height / image.naturalHeight);
  const renderedWidth = image.naturalWidth * scale;
  const renderedHeight = image.naturalHeight * scale;
  const renderedLeft = rect.left + (rect.width - renderedWidth) / 2;
  const renderedTop = rect.top + (rect.height - renderedHeight) / 2;

  return (
    event.clientX < renderedLeft ||
    event.clientX > renderedLeft + renderedWidth ||
    event.clientY < renderedTop ||
    event.clientY > renderedTop + renderedHeight
  );
}

function bindEvents() {
  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      if (tab.dataset.tab === "practice") {
        clearStudyFilters();
        state.showStudyMap = true;
        renderStudyMap();
      }
      activateTab(tab.dataset.tab);
    });
  });
  if (fields.userForm && fields.userNameInput) {
    fields.userForm.addEventListener("submit", (event) => {
      event.preventDefault();
      switchUser(fields.userNameInput.value);
    });
    fields.userNameInput.addEventListener("change", () => {
      switchUser(fields.userNameInput.value);
    });
  }
  fields.userAdminForm.addEventListener("submit", createManagedUser);
  fields.userTable.addEventListener("click", handleUserTableClick);
  fields.examTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-exam]");
    if (button) switchExam(button.dataset.exam);
  });
  $$(".study-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.studyMode = tab.dataset.studyMode;
      renderStudyMap();
    });
  });
  fields.studyList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-study-index]");
    if (button) startStudyItem(Number(button.dataset.studyIndex));
  });
  fields.startAllRandom?.addEventListener("click", () => {
    startPractice({}, { forceRandom: true });
  });
  fields.practiceResultFilter?.addEventListener("change", (event) => {
    const input = event.target.closest("[data-practice-result-filter]");
    if (!input) return;
    const mark = input.dataset.practiceResultFilter;
    if (input.checked) {
      state.practiceStartResultFilter.add(mark);
    } else {
      state.practiceStartResultFilter.delete(mark);
    }
    renderPracticeResultFilter();
  });
  fields.practiceRandomToggle?.addEventListener("change", () => {
    state.practiceRandomStart = fields.practiceRandomToggle.checked;
    try {
      window.localStorage.setItem(RANDOM_START_STORAGE_KEY, state.practiceRandomStart ? "1" : "0");
    } catch {
      // 保存できない環境では次回起動時に既定値へ戻るだけで、演習には影響しない。
    }
  });
  fields.backToStudyMap.addEventListener("click", () => {
    clearStudyFilters();
    showStudyMap();
    renderStudyMap();
    resetScroll();
  });
  $("#applyFilters").addEventListener("click", () => {
    state.localFilter = null;
    if (!(state.activeTab === "practice" && !state.showStudyMap)) {
      state.practiceResultFilter = null;
    }
    state.practiceOrder = null;
    state.practiceShufflePending = false;
    state.libraryPage = 1;
    state.showStudyMap = false;
    renderFilterSummary();
    refreshAll();
  });
  fields.filterYear.addEventListener("change", renderFilterSummary);
  fields.filterCategory.addEventListener("change", renderFilterSummary);
  fields.filterKeyword.addEventListener("input", renderFilterSummary);
  window.addEventListener("resize", updateFilterPanelOpen);
  fields.jumpForm.addEventListener("submit", jumpToQuestion);
  fields.prevQuestion.addEventListener("click", pickPreviousQuestion);
  fields.nextQuestion.addEventListener("click", pickNextQuestion);
  fields.questionImages.addEventListener("click", (event) => {
    const trigger = event.target.closest(".question-image-trigger");
    if (trigger) openImageLightbox(trigger);
  });
  fields.closeImageLightbox?.addEventListener("click", () => closeImageLightbox());
  fields.imageLightbox?.addEventListener("click", (event) => {
    if (isImageLightboxBackgroundClick(event)) closeImageLightbox();
  });
  fields.imageLightbox?.addEventListener("close", () => closeImageLightbox());
  $("#answerForm").addEventListener("submit", submitAnswer);
  fields.noteForm?.addEventListener("submit", saveQuestionNote);
  $("#clearAnswer").addEventListener("click", renderPractice);
  fields.resultBox.addEventListener("click", handleResultBoxClick);
  fields.savePracticeCategory?.addEventListener("click", savePracticeCategory);
  fields.libraryPrevPage?.addEventListener("click", () => setLibraryPage(state.libraryPage - 1));
  fields.libraryNextPage?.addEventListener("click", () => setLibraryPage(state.libraryPage + 1));
  fields.libraryFilter?.addEventListener("change", (event) => {
    const input = event.target.closest("[data-result-filter]");
    if (!input) return;
    const mark = input.dataset.resultFilter;
    if (input.checked) {
      state.libraryResultFilter.add(mark);
    } else {
      state.libraryResultFilter.delete(mark);
    }
    state.libraryPage = 1;
    renderQuestionTable();
  });
  fields.questionTable.addEventListener("click", (event) => {
    const practiceButton = event.target.closest("[data-practice]");
    if (practiceButton) {
      practiceQuestionFromLibrary(Number(practiceButton.dataset.practice));
    }
  });
  fields.historyTable.addEventListener("click", (event) => {
    const button = event.target.closest("[data-delete-attempt]");
    if (button) deleteHistoryAttempt(Number(button.dataset.deleteAttempt));
  });
  fields.clearHistory?.addEventListener("click", deleteAllHistory);
}

function isKeyboardInput(element) {
  if (!element) return false;
  if (element.tagName === "TEXTAREA") return true;
  if (element.tagName !== "INPUT") return false;
  return !["checkbox", "radio", "button", "submit", "reset", "range", "file"].includes(element.type);
}

// ソフトキーボード表示中はfixedの下部タブがキーボード上に浮くため隠す。
// ビューポート高さでの判定はiOSのツールバー開閉と区別できず誤検知するので、
// テキスト入力へのフォーカスだけを判定条件にする。
function syncKeyboardOpenState() {
  document.body.classList.toggle("keyboard-open", isKeyboardInput(document.activeElement));
}

function bindKeyboardWatcher() {
  document.addEventListener("focusin", syncKeyboardOpenState);
  document.addEventListener("focusout", () => {
    window.setTimeout(syncKeyboardOpenState, 60);
  });
}

bindKeyboardWatcher();
bindEvents();
// セッション(ユーザー確定・権限)は接続方法が変わらない限り不変なので初回だけ取得する。
refreshSession()
  .then(() => refreshAll())
  .catch((error) => toast(error.message));
