const DEFAULT_USER_NAME = "自分";
const USER_STORAGE_KEY = "kakomon-trainer-user";
const LIBRARY_PAGE_SIZE = 40;
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
  localFilter: null,
  resultContext: null,
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
    "神経・頭頸部",
    "骨軟部",
    "胸部",
    "心大血管",
    "乳腺",
    "腹部",
    "泌尿器・婦人科",
    "小児",
    "IVR",
    "核医学",
    "基礎・安全・情報",
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
  choiceList: $("#choiceList"),
  freeAnswerWrap: $("#freeAnswerWrap"),
  freeAnswer: $("#freeAnswer"),
  resultBox: $("#resultBox"),
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
  return applyResultFilter(baseQuestionList(), state.practiceResultFilter);
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
  await refreshSession();
  const query = selectedFilters();
  const statsParams = userScopedParams();
  if (state.selectedExam) statsParams.set("exam", state.selectedExam);
  const summaryParams = userScopedParams();
  if (state.selectedExam) summaryParams.set("exam", state.selectedExam);
  const historyParams = userScopedParams({ limit: "80" });
  if (state.selectedExam) historyParams.set("exam", state.selectedExam);
  const shouldLoadQuestions =
    forceLoadQuestions || !state.showStudyMap || state.activeTab === "library" || hasActiveQuestionFilter();
  const [stats, summaryPayload, questionPayload, historyPayload] = await Promise.all([
    api(`/api/stats${queryFor(statsParams)}`),
    api(`/api/study-summary${queryFor(summaryParams)}`),
    shouldLoadQuestions ? api(`/api/questions${query ? `?${query}` : ""}`) : Promise.resolve(null),
    api(`/api/attempts${queryFor(historyParams)}`),
  ]);

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
    state.questionsLoaded = true;
  } else {
    clearQuestionLists();
  }
  renderStats();
  renderExamTabs();
  renderFilters();
  renderStudyMap();
  renderQuestionTable();
  renderHistory(historyPayload.attempts || []);
  if (state.session?.can_manage_users) {
    await refreshUsers();
  } else {
    state.users = [];
    renderUsers();
  }

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
      return `<span class="study-progress-${name}" style="width: ${width}%"></span>`;
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

  $$(".study-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.studyMode === state.studyMode);
  });
  renderPracticeResultFilter();
}

function renderPracticeResultFilter() {
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

function startStudyItem(index) {
  const item = state.studyItems[index];
  if (!item) return;
  const filter = item.filter || {};
  state.localFilter = filter.localFilter || null;
  state.practiceResultFilter = copyResultFilter(state.practiceStartResultFilter);
  fields.filterYear.value = filter.year || "";
  fields.filterCategory.value = filter.category || "";
  fields.filterKeyword.value = filter.q || "";
  state.libraryPage = 1;
  state.showStudyMap = false;
  renderFilterSummary();
  refreshAll({ keepQuestion: false }).catch((error) => toast(error.message));
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

function setCurrentQuestionByIndex(index) {
  if (!state.questions.length) {
    showPracticeSession();
    state.currentQuestion = null;
    state.currentIndex = -1;
    renderPractice();
    return;
  }

  state.currentIndex = (index + state.questions.length) % state.questions.length;
  state.currentQuestion = state.questions[state.currentIndex];
  showPracticeSession();
  renderPractice();
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
  const question = state.currentQuestion;
  state.resultContext = null;
  fields.resultBox.className = "result-box hidden";
  fields.resultBox.textContent = "";
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
        <img src="${escapeHtml(src)}" alt="問題画像 ${index + 1}" loading="lazy">
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
            <input type="${inputType}" name="choiceAnswer" value="${escapeHtml(choice)}">
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

function renderAttemptChoiceHistory(attempts = []) {
  if (!attempts.length) return "";
  const rows = attempts
    .map((attempt) => {
      const date = new Date(attempt.created_at).toLocaleString("ja-JP");
      const mark = attempt.self_mark || "warn";
      return `
        <li class="attempt-history-row">
          <span class="result-mark ${markClass(mark)}">${markLabel(mark)}</span>
          <span class="attempt-answer">${escapeHtml(attempt.user_answer)}</span>
          <time>${escapeHtml(date)}</time>
        </li>
      `;
    })
    .join("");
  return `
    <div class="attempt-history">
      <div class="attempt-history-title">選択履歴</div>
      <ol>${rows}</ol>
    </div>
  `;
}

function renderAnswerResult(result) {
  state.resultContext = { ...(state.resultContext || {}), ...result };
  const context = state.resultContext;
  const mark = context.self_mark || "warn";
  const resultClass = context.graded ? (context.correct ? "correct" : "wrong") : "correct";
  const heading = context.graded
    ? context.correct
      ? "正解"
      : "不正解"
    : context.saved
      ? "解答を記録しました"
      : "解答を確認しました";
  const answerBlock = context.graded
    ? `<div>正答: ${escapeHtml(context.correct_answer)}</div>`
    : `<div>この問題は正答未登録です。一覧の編集から正答を追加できます。</div>`;
  const userAnswerBlock = context.user_answer ? `<div>あなたの解答: ${escapeHtml(context.user_answer)}</div>` : "";
  const registerAction = context.saved
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
    ${context.explanation ? `<div>${escapeHtml(context.explanation).replaceAll("\n", "<br>")}</div>` : ""}
    ${renderMarkButtons(context.attempt_id, mark)}
    ${context.saved ? renderAttemptChoiceHistory(context.attempts || []) : ""}
    ${registerAction}
  `;
}

async function submitAnswer(event) {
  event.preventDefault();
  if (!state.currentQuestion) return;

  const userAnswer = currentAnswer();
  if (!userAnswer) {
    toast("解答を入力してください。");
    return;
  }

  const hasAnswer = Boolean(String(state.currentQuestion.answer || "").trim());
  const correct = hasAnswer ? isCorrectAnswer(userAnswer, state.currentQuestion.answer) : null;
  renderAnswerResult({
    attempt_id: null,
    saved: false,
    question_id: state.currentQuestion.id,
    user_answer: userAnswer,
    self_mark: hasAnswer ? (correct ? "ok" : "wrong") : "warn",
    graded: hasAnswer,
    correct,
    correct_answer: state.currentQuestion.answer,
    explanation: state.currentQuestion.explanation,
    attempts: [],
  });
  setAnswerControlsDisabled(true);
}

async function registerPendingResult() {
  const context = state.resultContext;
  if (!context || context.saved || context.registering) return;
  if (!context.question_id || !context.user_answer) {
    toast("先に判定してください。");
    return;
  }

  const previousQuestionId = state.currentQuestion?.id || context.question_id;
  const previousIndex = state.currentIndex;
  state.resultContext = { ...context, registering: true };
  try {
    await api("/api/attempts", {
      method: "POST",
      body: JSON.stringify({
        question_id: context.question_id,
        user_name: state.currentUser,
        user_answer: context.user_answer,
        self_mark: context.self_mark || "warn",
      }),
    });
    await refreshAll({ keepQuestion: true, renderPracticePanel: false });
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
    await refreshAll({ keepQuestion: true, renderPracticePanel: false });
    syncCurrentQuestion();
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
  if (name === "users") {
    refreshUsers().catch((error) => toast(error.message));
  }
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
  fields.backToStudyMap.addEventListener("click", () => {
    clearStudyFilters();
    showStudyMap();
    renderStudyMap();
  });
  $("#applyFilters").addEventListener("click", () => {
    state.localFilter = null;
    if (!(state.activeTab === "practice" && !state.showStudyMap)) {
      state.practiceResultFilter = null;
    }
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

bindEvents();
refreshAll().catch((error) => toast(error.message));
