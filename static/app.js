const DEFAULT_USER_NAME = "自分";
const USER_STORAGE_KEY = "kakomon-trainer-user";
const LIBRARY_PAGE_SIZE = 40;
const QUESTION_ATTEMPT_HISTORY_LIMIT = 30;
const QUESTION_SET_ROUND_PAGE_SIZE = 20;
const QUESTION_SET_ROUND_ITEM_PAGE_SIZE = 100;
const DISEASE_CHECKLIST_PAGE_SIZE = 12;
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
  practiceSession: null,
  practiceSessionActive: false,
  practiceStarting: false,
  practiceFlowRequestId: 0,
  practiceSessionRequestId: 0,
  refreshRequestId: 0,
  questionSets: [],
  questionSetsLoaded: false,
  questionSetsLoading: false,
  questionSetsError: "",
  questionSetView: "list",
  selectedQuestionSetId: null,
  questionSetRounds: [],
  questionSetRoundsTotal: 0,
  questionSetRoundsOffset: 0,
  selectedQuestionSetRoundId: null,
  questionSetRoundDetail: null,
  questionSetRoundItems: [],
  questionSetRoundItemsTotal: 0,
  questionSetRoundItemsOffset: 0,
  questionSetPractice: null,
  questionSetPracticeActive: false,
  questionSetRequestId: 0,
  questionSetHistoryRequestId: 0,
  questionSetDetailRequestId: 0,
  questionSetFlowRequestId: 0,
  diseaseChecklists: [],
  diseaseChecklistsLoaded: false,
  diseaseChecklistsLoading: false,
  diseaseChecklistsError: "",
  selectedDiseaseChecklistId: null,
  diseaseChecklistDetail: null,
  diseaseChecklistDetailLoading: false,
  diseaseChecklistDetailError: "",
  diseaseChecklistStatusFilter: "unreviewed",
  diseaseChecklistRegionFilter: "",
  diseaseChecklistPage: 1,
  diseaseChecklistSearchFilter: "",
  diseaseChecklistEverWrongFilter: false,
  diseaseChecklistAddedByWrongFilter: false,
  diseaseChecklistRecentlyReviewedItemId: null,
  diseaseChecklistUpdatingItemIds: new Set(),
  diseaseChecklistContextRequestId: 0,
  diseaseChecklistListRequestId: 0,
  diseaseChecklistDetailRequestId: 0,
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

const DISEASE_CHECKLIST_STATUSES = new Set(["ok", "warn", "wrong"]);

const RESULT_FILTER_ORDER = ["ok", "warn", "wrong", "untried"];

const KNOWN_EXAMS = ["放射線診断専門医認定試験", "核医学専門医試験", "放射線治療専門医認定試験"];

const EXAM_LABELS = {
  放射線診断専門医認定試験: "診断専門医",
  核医学専門医試験: "核医学専門医",
  放射線治療専門医認定試験: "治療専門医",
};

const DIAGNOSTIC_UNOFFICIAL_ANSWER_URLS = new Map([
  ["2015", "https://radiology-exam.com/?page_id=43"],
  ["2016", "https://radiology-exam.com/?page_id=41"],
  ["2017", "https://radiology-exam.com/?page_id=39"],
  ["2018", "https://radiology-exam.com/?page_id=37"],
  ["2019", "https://radiology-exam.com/?page_id=35"],
  ["2020", "https://radiology-exam.com/?page_id=64"],
  ["2021", "https://radiology-exam.com/?page_id=135"],
  ["2022", "https://radiology-exam.com/?page_id=264"],
  ["2023", "https://radiology-exam.com/?page_id=334"],
  ["2024", "https://radiology-exam.com/?page_id=385"],
  ["2025", "https://radiology-exam.com/?page_id=504"],
]);

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
  diseaseChecklistTab: $("#diseaseChecklistTab"),
  diseaseChecklistMessage: $("#diseaseChecklistMessage"),
  diseaseChecklistContent: $("#diseaseChecklistContent"),
  diseaseChecklistSelect: $("#diseaseChecklistSelect"),
  diseaseChecklistSummary: $("#diseaseChecklistSummary"),
  diseaseStatusFilter: $("#diseaseStatusFilter"),
  diseaseRegionFilter: $("#diseaseRegionFilter"),
  diseasePreviousRegion: $("#diseasePreviousRegion"),
  diseaseNextRegion: $("#diseaseNextRegion"),
  diseaseAreaPageStatus: $("#diseaseAreaPageStatus"),
  diseaseSearchFilter: $("#diseaseSearchFilter"),
  diseaseEverWrongFilter: $("#diseaseEverWrongFilter"),
  diseaseAddedByWrongFilter: $("#diseaseAddedByWrongFilter"),
  diseaseChecklistResultCount: $("#diseaseChecklistResultCount"),
  diseaseChecklistPaginationTop: $("#diseaseChecklistPaginationTop"),
  diseaseChecklistPaginationBottom: $("#diseaseChecklistPaginationBottom"),
  diseaseChecklistCards: $("#diseaseChecklistCards"),
  refreshDiseaseChecklists: $("#refreshDiseaseChecklists"),
  exportDiseaseChecklist: $("#exportDiseaseChecklist"),
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
  practiceSessionCard: $("#practiceSessionCard"),
  studyList: $("#studyList"),
  questionSetPanel: $("#questionSetPanel"),
  questionSetListView: $("#questionSetListView"),
  questionSetCards: $("#questionSetCards"),
  refreshQuestionSets: $("#refreshQuestionSets"),
  questionSetHistoryView: $("#questionSetHistoryView"),
  questionSetHistoryTitle: $("#questionSetHistoryTitle"),
  questionSetRoundList: $("#questionSetRoundList"),
  questionSetRoundPagination: $("#questionSetRoundPagination"),
  questionSetRoundPrev: $("#questionSetRoundPrev"),
  questionSetRoundNext: $("#questionSetRoundNext"),
  questionSetRoundPageStatus: $("#questionSetRoundPageStatus"),
  questionSetRoundDetailView: $("#questionSetRoundDetailView"),
  questionSetRoundDetailTitle: $("#questionSetRoundDetailTitle"),
  questionSetRoundDetailSummary: $("#questionSetRoundDetailSummary"),
  questionSetRoundItems: $("#questionSetRoundItems"),
  questionSetRoundItemPagination: $("#questionSetRoundItemPagination"),
  questionSetRoundItemPrev: $("#questionSetRoundItemPrev"),
  questionSetRoundItemNext: $("#questionSetRoundItemNext"),
  questionSetRoundItemPageStatus: $("#questionSetRoundItemPageStatus"),
  practiceSession: $("#practiceSession"),
  practiceRoundProgress: $("#practiceRoundProgress"),
  practiceRoundComplete: $("#practiceRoundComplete"),
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

function diagnosticUnofficialAnswerLink(question) {
  if (question?.exam !== "放射線診断専門医認定試験") return null;
  const year = String(question.year ?? "").trim();
  const url = DIAGNOSTIC_UNOFFICIAL_ANSWER_URLS.get(year);
  return url ? { year, url } : null;
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

function normalizePracticeSession(value) {
  if (!value || typeof value !== "object") return null;
  const questionIds = Array.isArray(value.question_ids)
    ? value.question_ids.map(Number).filter(Number.isInteger)
    : [];
  const completedQuestionIds = Array.isArray(value.completed_question_ids)
    ? value.completed_question_ids.map(Number).filter(Number.isInteger)
    : [];
  const completed = Number(value.completed ?? completedQuestionIds.length);
  const total = Number(value.total ?? questionIds.length);
  return {
    ...value,
    filters: value.filters && typeof value.filters === "object" ? value.filters : {},
    question_ids: questionIds,
    completed_question_ids: completedQuestionIds,
    total,
    completed,
    remaining: Number(value.remaining ?? Math.max(0, total - completed)),
  };
}

function normalizeQuestionSetRound(value, fallback = null) {
  if (!value || typeof value !== "object") return null;
  const fallbackRound = fallback && typeof fallback === "object" ? fallback : {};
  const summary = value.summary && typeof value.summary === "object" ? value.summary : {};
  const source = { ...summary, ...value };
  const questionIds = Array.isArray(value.question_ids)
    ? value.question_ids.map(Number).filter(Number.isInteger)
    : Array.isArray(fallbackRound.question_ids)
      ? [...fallbackRound.question_ids]
      : [];
  const completedQuestionIds = Array.isArray(value.completed_question_ids)
    ? value.completed_question_ids.map(Number).filter(Number.isInteger)
    : Array.isArray(fallbackRound.completed_question_ids)
      ? [...fallbackRound.completed_question_ids]
      : [];
  const total = Math.max(0, Number(source.total ?? fallbackRound.total ?? questionIds.length));
  const completed = Math.min(
    total,
    Math.max(0, Number(source.completed ?? fallbackRound.completed ?? completedQuestionIds.length)),
  );
  const selfMarks = source.self_marks && typeof source.self_marks === "object"
    ? source.self_marks
    : fallbackRound.self_marks || {};
  const rawStatus = source.status || fallbackRound.status || "active";
  const status = ["active", "completed", "abandoned"].includes(rawStatus) ? rawStatus : "active";
  return {
    ...fallbackRound,
    ...source,
    id: Number(source.id ?? fallbackRound.id),
    round_number: Number(source.round_number ?? fallbackRound.round_number ?? 0),
    status,
    total,
    completed,
    remaining: Math.max(0, Number(source.remaining ?? fallbackRound.remaining ?? total - completed)),
    unavailable: Math.max(0, Number(source.unavailable ?? fallbackRound.unavailable ?? 0)),
    graded: Math.max(0, Number(source.graded ?? fallbackRound.graded ?? 0)),
    correct: Math.max(0, Number(source.correct ?? fallbackRound.correct ?? 0)),
    rate: Number(source.rate ?? fallbackRound.rate ?? 0),
    self_marks: {
      ok: Math.max(0, Number(selfMarks.ok || 0)),
      warn: Math.max(0, Number(selfMarks.warn || 0)),
      wrong: Math.max(0, Number(selfMarks.wrong || 0)),
    },
    question_ids: questionIds,
    completed_question_ids: completedQuestionIds,
    next_question_id: Object.prototype.hasOwnProperty.call(value, "next_question_id")
      ? value.next_question_id == null
        ? null
        : Number(value.next_question_id)
      : fallbackRound.next_question_id ?? null,
  };
}

function normalizeQuestionSet(value) {
  if (!value || typeof value !== "object") return null;
  return {
    ...value,
    id: Number(value.id),
    title: String(value.title || "名称未設定"),
    exam: String(value.exam || ""),
    total: Math.max(0, Number(value.total || 0)),
    rounds_count: Math.max(0, Number(value.rounds_count || 0)),
    active_round: normalizeQuestionSetRound(value.active_round),
    latest_round: normalizeQuestionSetRound(value.latest_round),
  };
}

function questionSetById(id) {
  const normalizedId = Number(id);
  return state.questionSets.find((item) => item.id === normalizedId) || null;
}

function normalizeDiseaseChecklistStatus(value) {
  return DISEASE_CHECKLIST_STATUSES.has(value) ? value : null;
}

function normalizeDiseaseChecklistSummary(value) {
  if (!value || typeof value !== "object") return null;
  const counts = value.status_counts && typeof value.status_counts === "object" ? value.status_counts : {};
  const itemCount = Math.max(0, Number(value.item_count || 0));
  return {
    ...value,
    id: Number(value.id),
    title: String(value.title || "名称未設定"),
    exam: String(value.exam || ""),
    item_count: itemCount,
    base_item_count: Math.max(0, Number(value.base_item_count ?? itemCount)),
    ever_wrong_count: Math.max(0, Number(value.ever_wrong_count || 0)),
    added_by_wrong_count: Math.max(0, Number(value.added_by_wrong_count || 0)),
    status_counts: {
      unreviewed: Math.max(0, Number(counts.unreviewed ?? itemCount)),
      ok: Math.max(0, Number(counts.ok || 0)),
      warn: Math.max(0, Number(counts.warn || 0)),
      wrong: Math.max(0, Number(counts.wrong || 0)),
    },
  };
}

function normalizeDiseaseChecklistItem(value) {
  if (!value || typeof value !== "object") return null;
  return {
    ...value,
    id: Number(value.id),
    position: Math.max(0, Number(value.position || 0)),
    disease_name: String(value.disease_name || "名称未設定"),
    primary_region: String(value.primary_region || "未分類"),
    hierarchy: value.hierarchy ?? "",
    review_note: String(value.review_note || ""),
    sources: Array.isArray(value.sources) ? value.sources : [],
    status: normalizeDiseaseChecklistStatus(value.status),
    ever_wrong: value.ever_wrong === true,
    added_by_wrong: value.added_by_wrong === true,
  };
}

function normalizeDiseaseChecklist(value) {
  const summary = normalizeDiseaseChecklistSummary(value);
  if (!summary) return null;
  const items = Array.isArray(value.items)
    ? value.items.map(normalizeDiseaseChecklistItem).filter((item) => Number.isInteger(item?.id))
    : [];
  return { ...summary, items };
}

function diseaseChecklistById(id) {
  const normalizedId = Number(id);
  return state.diseaseChecklists.find((item) => item.id === normalizedId) || null;
}

function canUseDiseaseChecklists() {
  return state.session?.can_manage_users === true;
}

function hasActivePracticeSession() {
  return Boolean(state.practiceSessionActive && state.practiceSession?.token);
}

function hasActiveQuestionSetRound() {
  return Boolean(
    hasQuestionSetPracticeContext() &&
      state.questionSetPractice.round.status === "active",
  );
}

function hasQuestionSetPracticeContext() {
  return Boolean(state.questionSetPracticeActive && state.questionSetPractice?.round?.token);
}

function practiceSessionInProgress(session = state.practiceSession) {
  return Boolean(session?.token && Number(session.remaining || 0) > 0 && session.status !== "completed");
}

function practiceFiltersSnapshot() {
  return {
    year: fields.filterYear.value || "",
    category: fields.filterCategory.value || "",
    q: fields.filterKeyword.value.trim(),
    result_marks: state.practiceResultFilter?.size ? [...state.practiceResultFilter] : [],
    local_filter: state.localFilter ? { ...state.localFilter } : {},
  };
}

function setFilterSelectValue(select, value) {
  const normalizedValue = String(value || "");
  if (normalizedValue && !Array.from(select.options).some((option) => option.value === normalizedValue)) {
    const option = document.createElement("option");
    option.value = normalizedValue;
    option.textContent = normalizedValue;
    select.append(option);
  }
  select.value = normalizedValue;
}

function applySavedPracticeFilters(filters = {}) {
  setFilterSelectValue(fields.filterYear, filters.year);
  setFilterSelectValue(fields.filterCategory, filters.category);
  fields.filterKeyword.value = filters.q || "";
  state.localFilter =
    filters.local_filter && typeof filters.local_filter === "object" && Object.keys(filters.local_filter).length
      ? { ...filters.local_filter }
      : null;
  const resultMarks = Array.isArray(filters.result_marks)
    ? filters.result_marks.filter((mark) => RESULT_FILTER_ORDER.includes(mark))
    : [];
  state.practiceStartResultFilter = new Set(resultMarks);
  state.practiceResultFilter = resultMarks.length ? new Set(resultMarks) : null;
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

function practiceSessionQuestions() {
  const session = state.practiceSession;
  if (!hasActivePracticeSession() || !session) return null;
  const questionsById = new Map(state.allQuestions.map((question) => [Number(question.id), question]));
  const completed = new Set(session.completed_question_ids);
  return session.question_ids
    .filter((id) => !completed.has(id))
    .map((id) => questionsById.get(id))
    .filter(Boolean);
}

function questionSetRoundQuestions() {
  const round = state.questionSetPractice?.round;
  if (!hasQuestionSetPracticeContext() || !round) return null;
  const questionsById = new Map(state.allQuestions.map((question) => [Number(question.id), question]));
  const completed = new Set(round.completed_question_ids);
  return round.question_ids
    .filter((id) => !completed.has(id))
    .map((id) => questionsById.get(id))
    .filter(Boolean);
}

function filteredPracticeQuestions() {
  const questionSetQuestions = questionSetRoundQuestions();
  if (questionSetQuestions) return questionSetQuestions;
  const sessionQuestions = practiceSessionQuestions();
  if (sessionQuestions) return sessionQuestions;
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

function practiceSessionParams(user = state.currentUser, exam = state.selectedExam) {
  const params = new URLSearchParams();
  params.set("user", user);
  if (exam) params.set("exam", exam);
  return params;
}

function questionSetParams(initial = {}, user = state.currentUser, exam = state.selectedExam) {
  const params = new URLSearchParams(initial);
  params.set("user", user);
  if (exam) params.set("exam", exam);
  return params;
}

function diseaseChecklistParams({ includeExam = false } = {}, user = state.currentUser, exam = state.selectedExam) {
  const params = new URLSearchParams();
  params.set("user", user);
  if (includeExam && exam) params.set("exam", exam);
  return params;
}

function clearDiseaseChecklistState() {
  state.diseaseChecklistContextRequestId += 1;
  state.diseaseChecklistListRequestId += 1;
  state.diseaseChecklistDetailRequestId += 1;
  state.diseaseChecklists = [];
  state.diseaseChecklistsLoaded = false;
  state.diseaseChecklistsLoading = false;
  state.diseaseChecklistsError = "";
  state.selectedDiseaseChecklistId = null;
  state.diseaseChecklistDetail = null;
  state.diseaseChecklistDetailLoading = false;
  state.diseaseChecklistDetailError = "";
  state.diseaseChecklistStatusFilter = "unreviewed";
  state.diseaseChecklistRegionFilter = "";
  state.diseaseChecklistPage = 1;
  state.diseaseChecklistSearchFilter = "";
  state.diseaseChecklistEverWrongFilter = false;
  state.diseaseChecklistAddedByWrongFilter = false;
  state.diseaseChecklistRecentlyReviewedItemId = null;
  state.diseaseChecklistUpdatingItemIds = new Set();
}

function diseaseChecklistStatusMeta(status) {
  if (status === "ok") return { label: "○", text: "知っている", className: "ok" };
  if (status === "warn") return { label: "△", text: "要確認", className: "warn" };
  if (status === "wrong") return { label: "×", text: "知らない", className: "wrong" };
  return { label: "未", text: "未確認", className: "unreviewed" };
}

function diseaseHierarchyParts(value) {
  if (Array.isArray(value)) {
    return value.flatMap((item) => diseaseHierarchyParts(item));
  }
  if (!value || typeof value !== "object") {
    const text = String(value ?? "").trim();
    return text ? [text] : [];
  }
  const orderedKeys = [
    "chapter",
    "major",
    "middle",
    "small",
    "章",
    "大項目",
    "中項目",
    "小項目",
  ];
  const consumed = new Set(["no", "No", "No.", "source_no"]);
  const sourceNo = value.no ?? value.No ?? value["No."] ?? value.source_no;
  const parts = sourceNo == null || String(sourceNo).trim() === "" ? [] : [`No.${String(sourceNo).trim()}`];
  orderedKeys.forEach((key) => {
    if (!Object.prototype.hasOwnProperty.call(value, key) || consumed.has(key)) return;
    consumed.add(key);
    const text = String(value[key] ?? "").trim();
    if (text && parts.at(-1) !== text) parts.push(text);
  });
  Object.entries(value).forEach(([key, raw]) => {
    if (consumed.has(key)) return;
    const text = String(raw ?? "").trim();
    if (text && parts.at(-1) !== text) parts.push(text);
  });
  return parts;
}

function diseaseHierarchyText(value) {
  if (Array.isArray(value)) {
    return value
      .map((item) => diseaseHierarchyParts(item).join(" › "))
      .filter(Boolean)
      .join(" / ");
  }
  return diseaseHierarchyParts(value).join(" › ");
}

function diseaseSourceText(source) {
  if (!source || typeof source !== "object") return String(source ?? "").trim();
  const no = source.no ?? source.No ?? source["No."] ?? source.source_no;
  const parts = [
    source.chapter ?? source["章"],
    source.major ?? source["大項目"],
    source.middle ?? source["中項目"],
    source.small ?? source["小項目"],
  ]
    .map((item) => String(item ?? "").trim())
    .filter(Boolean)
    .filter((item, index, values) => index === 0 || item !== values[index - 1]);
  const prefix = no == null || String(no).trim() === "" ? "" : `No.${String(no).trim()}`;
  const curriculumText = [prefix, ...parts].filter(Boolean).join(" › ");
  if (curriculumText) return curriculumText;
  const label = String(source.label ?? source.title ?? source.name ?? "").trim();
  const url = String(source.url ?? "").trim();
  return label && url ? `${label} (${url})` : label || url;
}

function diseaseSourceHttpsUrl(source) {
  const rawUrl = typeof source === "string" ? source : source?.url;
  if (!rawUrl) return null;
  try {
    const url = new URL(String(rawUrl));
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function renderDiseaseSource(source) {
  const text = diseaseSourceText(source);
  const url = diseaseSourceHttpsUrl(source);
  if (!url) return escapeHtml(text);
  const label =
    (typeof source === "object"
      ? String(source.label ?? source.title ?? source.name ?? "").trim()
      : "") || url;
  return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
}

function normalizedDiseaseSearchText(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .toLocaleLowerCase("ja-JP")
    .replace(/\s+/g, " ")
    .trim();
}

function diseaseChecklistItemSearchText(item) {
  return normalizedDiseaseSearchText(
    [
      item.disease_name,
      item.primary_region,
      diseaseHierarchyText(item.hierarchy),
      item.review_note,
      ...item.sources.map(diseaseSourceText),
    ].join(" "),
  );
}

function diseaseChecklistRegions() {
  const seen = new Set();
  return [...(state.diseaseChecklistDetail?.items || [])]
    .sort((a, b) => a.position - b.position || a.id - b.id)
    .map((item) => String(item.primary_region || "").trim())
    .filter((region) => {
      if (!region || seen.has(region)) return false;
      seen.add(region);
      return true;
    });
}

function diseaseChecklistItemMatches(item, { ignoreStatus = false, ignoreRegion = false } = {}) {
  if (!ignoreStatus) {
    const selectedStatus = state.diseaseChecklistStatusFilter;
    if (selectedStatus === "unreviewed" && item.status !== null) return false;
    if (DISEASE_CHECKLIST_STATUSES.has(selectedStatus) && item.status !== selectedStatus) return false;
    if (selectedStatus === "review" && !["wrong", "warn"].includes(item.status)) {
      return false;
    }
  }
  if (
    !ignoreRegion &&
    state.diseaseChecklistRegionFilter &&
    item.primary_region !== state.diseaseChecklistRegionFilter
  ) {
    return false;
  }
  const query = normalizedDiseaseSearchText(state.diseaseChecklistSearchFilter);
  if (query && !diseaseChecklistItemSearchText(item).includes(query)) return false;
  if (state.diseaseChecklistEverWrongFilter && !item.ever_wrong) return false;
  if (state.diseaseChecklistAddedByWrongFilter && !item.added_by_wrong) return false;
  return true;
}

function filteredDiseaseChecklistItems() {
  const reviewRank = { wrong: 0, warn: 1 };
  const items = [...(state.diseaseChecklistDetail?.items || [])].sort((a, b) => {
    if (state.diseaseChecklistStatusFilter === "review") {
      const rankDifference = (reviewRank[a.status] ?? 2) - (reviewRank[b.status] ?? 2);
      if (rankDifference) return rankDifference;
    }
    return a.position - b.position || a.id - b.id;
  });
  const matching = items.filter((item) => diseaseChecklistItemMatches(item));
  const pageCount = Math.max(1, Math.ceil(matching.length / DISEASE_CHECKLIST_PAGE_SIZE));
  const requestedPage = Number.isInteger(state.diseaseChecklistPage)
    ? state.diseaseChecklistPage
    : 1;
  const page = Math.min(Math.max(1, requestedPage), pageCount);
  state.diseaseChecklistPage = page;
  const pageStart = (page - 1) * DISEASE_CHECKLIST_PAGE_SIZE;
  const pageEnd = Math.min(pageStart + DISEASE_CHECKLIST_PAGE_SIZE, matching.length);
  const pageItems = matching.slice(pageStart, pageEnd);
  const recentId = Number(state.diseaseChecklistRecentlyReviewedItemId);
  const recent = items.find((item) => item.id === recentId);
  const showRecent = Boolean(
    recent &&
      state.diseaseChecklistStatusFilter === "unreviewed" &&
      !matching.some((item) => item.id === recent.id) &&
      diseaseChecklistItemMatches(recent, { ignoreStatus: true }),
  );
  const visible = (showRecent ? [recent, ...pageItems] : pageItems).slice(
    0,
    DISEASE_CHECKLIST_PAGE_SIZE,
  );
  return { matching, visible, showRecent, page, pageCount, pageStart, pageEnd };
}

function diseaseChecklistCounts(items) {
  const counts = { unreviewed: 0, ok: 0, warn: 0, wrong: 0 };
  (items || []).forEach((item) => {
    const key = item.status || "unreviewed";
    counts[key] += 1;
  });
  return counts;
}

function replaceDiseaseChecklistSummary(value) {
  const summary = normalizeDiseaseChecklistSummary(value);
  if (!summary || !Number.isInteger(summary.id)) return;
  state.diseaseChecklists = state.diseaseChecklists.map((item) =>
    item.id === summary.id ? summary : item,
  );
  if (state.diseaseChecklistDetail?.id === summary.id) {
    state.diseaseChecklistDetail = {
      ...state.diseaseChecklistDetail,
      ...summary,
      items: state.diseaseChecklistDetail.items,
    };
  }
}

function renderDiseaseChecklistSummary() {
  if (!fields.diseaseChecklistSummary) return;
  const detail = state.diseaseChecklistDetail;
  if (!detail) {
    fields.diseaseChecklistSummary.innerHTML = "";
    return;
  }
  const counts = detail.status_counts || diseaseChecklistCounts(detail.items);
  fields.diseaseChecklistSummary.innerHTML = `
    <span class="unreviewed">未 ${Number(counts.unreviewed || 0)}</span>
    <span class="ok">○ ${Number(counts.ok || 0)}</span>
    <span class="warn">△ ${Number(counts.warn || 0)}</span>
    <span class="wrong">× ${Number(counts.wrong || 0)}</span>
    <span>基本 ${Number(detail.base_item_count || 0)}</span>
    <span>誤答経験 ${Number(detail.ever_wrong_count || 0)}</span>
    <span>誤答追加 ${Number(detail.added_by_wrong_count || 0)}</span>
  `;
}

function renderDiseaseChecklistRegionOptions() {
  if (!fields.diseaseRegionFilter) return;
  const regions = diseaseChecklistRegions();
  if (!regions.includes(state.diseaseChecklistRegionFilter)) {
    state.diseaseChecklistRegionFilter = regions[0] || "";
    state.diseaseChecklistPage = 1;
  }
  const filteredCounts = new Map(regions.map((region) => [region, 0]));
  (state.diseaseChecklistDetail?.items || [])
    .filter((item) => diseaseChecklistItemMatches(item, { ignoreRegion: true }))
    .forEach((item) => {
      const region = String(item.primary_region || "").trim();
      if (filteredCounts.has(region)) filteredCounts.set(region, filteredCounts.get(region) + 1);
    });
  fields.diseaseRegionFilter.innerHTML = regions
    .map((region) => {
      const selected = region === state.diseaseChecklistRegionFilter ? " selected" : "";
      const count = filteredCounts.get(region) || 0;
      return `<option value="${escapeHtml(region)}"${selected}>${escapeHtml(region)}（${count}件）</option>`;
    })
    .join("");
  fields.diseaseRegionFilter.toggleAttribute("disabled", regions.length === 0);

  const regionIndex = regions.indexOf(state.diseaseChecklistRegionFilter);
  fields.diseasePreviousRegion?.toggleAttribute("disabled", regionIndex <= 0);
  fields.diseaseNextRegion?.toggleAttribute(
    "disabled",
    regionIndex < 0 || regionIndex >= regions.length - 1,
  );
  if (fields.diseaseAreaPageStatus) {
    fields.diseaseAreaPageStatus.textContent =
      regionIndex >= 0 ? `分野 ${regionIndex + 1} / ${regions.length}` : "分野はありません";
  }
}

function renderDiseaseChecklistDetails(item) {
  if (!item.status) return "";
  const hierarchy = diseaseHierarchyText(item.hierarchy);
  const sources = item.sources.map(diseaseSourceText).filter(Boolean);
  const flags = [
    item.ever_wrong ? `<span>一度でも誤答</span>` : "",
    item.added_by_wrong ? `<span>誤答により追加</span>` : "",
  ]
    .filter(Boolean)
    .join("");
  return `
    <div class="disease-card-details">
      ${flags ? `<div class="disease-card-flags">${flags}</div>` : ""}
      ${hierarchy ? `<div><strong>カリキュラム</strong><p>${escapeHtml(hierarchy)}</p></div>` : ""}
      ${item.review_note ? `<div><strong>画像所見メモ</strong><p>${escapeHtml(item.review_note)}</p></div>` : ""}
      ${
        sources.length
          ? `<div><strong>出典</strong><ul>${item.sources
              .filter((source) => diseaseSourceText(source))
              .map((source) => `<li>${renderDiseaseSource(source)}</li>`)
              .join("")}</ul></div>`
          : ""
      }
      ${
        item.status === "wrong"
          ? `<p class="disease-review-hint">復習できたら「△ 復習した」で要確認へ移せます。</p>`
          : ""
      }
    </div>
  `;
}

function renderDiseaseChecklistCard(item) {
  const meta = diseaseChecklistStatusMeta(item.status);
  const updating = state.diseaseChecklistUpdatingItemIds.has(item.id);
  const recent = item.id === Number(state.diseaseChecklistRecentlyReviewedItemId);
  const warnText = item.status === "wrong" ? "△ 復習した" : "△ 要確認";
  return `
    <article class="disease-card ${item.status ? `reviewed ${meta.className}` : "unreviewed"}${recent ? " recently-reviewed" : ""}" data-disease-item-card="${item.id}">
      <div class="disease-card-head">
        <div>
          <h3>${escapeHtml(item.disease_name)}</h3>
          <span class="disease-region">${escapeHtml(item.primary_region)}</span>
        </div>
        ${item.status ? `<span class="disease-status ${meta.className}">${meta.label} ${meta.text}</span>` : ""}
      </div>
      ${renderDiseaseChecklistDetails(item)}
      <div class="disease-card-actions" role="group" aria-label="${escapeHtml(item.disease_name)}の評価">
        <button class="disease-status-button ok${item.status === "ok" ? " active" : ""}" type="button" data-disease-item-status="ok" data-disease-item-id="${item.id}" ${updating ? "disabled" : ""}>○ 知っている</button>
        <button class="disease-status-button warn${item.status === "warn" ? " active" : ""}" type="button" data-disease-item-status="warn" data-disease-item-id="${item.id}" ${updating ? "disabled" : ""}>${warnText}</button>
        <button class="disease-status-button wrong${item.status === "wrong" ? " active" : ""}" type="button" data-disease-item-status="wrong" data-disease-item-id="${item.id}" ${updating ? "disabled" : ""}>× 知らない</button>
      </div>
      ${recent && item.status ? `<button class="disease-next-unreviewed ghost small" type="button" data-disease-next-unreviewed>次の未確認へ</button>` : ""}
    </article>
  `;
}

function clearDiseaseChecklistPagination() {
  [fields.diseaseChecklistPaginationTop, fields.diseaseChecklistPaginationBottom].forEach(
    (container) => {
      if (!container) return;
      container.innerHTML = "";
      container.classList.add("hidden");
    },
  );
}

function clearDiseaseChecklistRegionNavigation() {
  if (fields.diseaseRegionFilter) {
    fields.diseaseRegionFilter.innerHTML = "";
    fields.diseaseRegionFilter.setAttribute("disabled", "");
  }
  fields.diseasePreviousRegion?.setAttribute("disabled", "");
  fields.diseaseNextRegion?.setAttribute("disabled", "");
  if (fields.diseaseAreaPageStatus) fields.diseaseAreaPageStatus.textContent = "";
}

function diseaseChecklistPaginationMarkup({ page, pageCount }) {
  const pageOptions = Array.from({ length: pageCount }, (_, index) => {
    const pageNumber = index + 1;
    const selected = pageNumber === page ? " selected" : "";
    return `<option value="${pageNumber}"${selected}>${pageNumber} / ${pageCount}</option>`;
  }).join("");
  return `
    <button class="ghost small" type="button" data-disease-page="${page - 1}" ${page <= 1 ? "disabled" : ""} aria-label="前の12件">前へ</button>
    <label class="disease-page-select">
      <span>ページ</span>
      <select data-disease-page-select aria-label="疾患一覧のページ">${pageOptions}</select>
    </label>
    <button class="ghost small" type="button" data-disease-page="${page + 1}" ${page >= pageCount ? "disabled" : ""} aria-label="次の12件">次へ</button>
  `;
}

function renderDiseaseChecklistPagination(result) {
  const containers = [
    fields.diseaseChecklistPaginationTop,
    fields.diseaseChecklistPaginationBottom,
  ].filter(Boolean);
  if (!result.matching.length || result.pageCount <= 1) {
    clearDiseaseChecklistPagination();
    return;
  }
  const markup = diseaseChecklistPaginationMarkup(result);
  containers.forEach((container) => {
    container.innerHTML = markup;
    container.classList.remove("hidden");
  });
}

function renderDiseaseChecklistCards() {
  if (!fields.diseaseChecklistCards || !fields.diseaseChecklistResultCount) return;
  const result = filteredDiseaseChecklistItems();
  const { matching, visible, showRecent, pageStart, pageEnd } = result;
  const selectedRegion = state.diseaseChecklistRegionFilter || "分野未選択";
  const rangeText = matching.length ? `${pageStart + 1}〜${pageEnd} / ${matching.length}件` : "0件";
  fields.diseaseChecklistResultCount.textContent = `${selectedRegion}：${rangeText}${
    showRecent ? "（直前の評価を先頭に表示）" : ""
  }`;
  renderDiseaseChecklistPagination(result);
  if (!visible.length) {
    fields.diseaseChecklistCards.innerHTML = `
      <div class="disease-checklist-message compact">
        <strong>条件に一致する疾患はありません</strong>
        <span>状態や分野ページの選択を変更してください。</span>
      </div>
    `;
    return;
  }
  fields.diseaseChecklistCards.innerHTML = visible.map(renderDiseaseChecklistCard).join("");
}

function renderDiseaseChecklistResults() {
  renderDiseaseChecklistRegionOptions();
  renderDiseaseChecklistCards();
}

function scrollDiseaseChecklistResultsIntoView() {
  fields.diseaseChecklistResultCount?.scrollIntoView({ block: "start", behavior: "smooth" });
}

function moveDiseaseChecklistRegion(direction) {
  const regions = diseaseChecklistRegions();
  const currentIndex = regions.indexOf(state.diseaseChecklistRegionFilter);
  const nextIndex = currentIndex + direction;
  if (nextIndex < 0 || nextIndex >= regions.length) return;
  state.diseaseChecklistRegionFilter = regions[nextIndex];
  state.diseaseChecklistPage = 1;
  state.diseaseChecklistRecentlyReviewedItemId = null;
  renderDiseaseChecklistResults();
  scrollDiseaseChecklistResultsIntoView();
}

function setDiseaseChecklistPage(value) {
  const page = Number(value);
  if (!Number.isInteger(page) || page < 1) return;
  state.diseaseChecklistPage = page;
  state.diseaseChecklistRecentlyReviewedItemId = null;
  renderDiseaseChecklistCards();
  scrollDiseaseChecklistResultsIntoView();
}

function handleDiseaseChecklistPaginationClick(event) {
  const button = event.target.closest("[data-disease-page]");
  if (button && !button.disabled) setDiseaseChecklistPage(button.dataset.diseasePage);
}

function handleDiseaseChecklistPaginationChange(event) {
  const select = event.target.closest("[data-disease-page-select]");
  if (select) setDiseaseChecklistPage(select.value);
}

function renderDiseaseChecklistView() {
  if (!fields.diseaseChecklistMessage || !fields.diseaseChecklistContent) return;
  const canUse = canUseDiseaseChecklists();
  fields.refreshDiseaseChecklists?.toggleAttribute(
    "disabled",
    !canUse || state.diseaseChecklistsLoading || state.diseaseChecklistDetailLoading,
  );
  if (!canUse) {
    fields.diseaseChecklistContent.classList.add("hidden");
    fields.diseaseChecklistMessage.classList.remove("hidden", "error");
    fields.diseaseChecklistMessage.innerHTML = "この画面は指定されたTailscale管理者専用です。";
    fields.exportDiseaseChecklist?.setAttribute("disabled", "");
    return;
  }
  if (state.diseaseChecklistsLoading && !state.diseaseChecklistsLoaded) {
    fields.diseaseChecklistContent.classList.add("hidden");
    fields.diseaseChecklistMessage.classList.remove("hidden", "error");
    fields.diseaseChecklistMessage.innerHTML = "疾患確認リストを読み込んでいます...";
    fields.exportDiseaseChecklist?.setAttribute("disabled", "");
    return;
  }
  if (state.diseaseChecklistsError && !state.diseaseChecklistsLoaded) {
    fields.diseaseChecklistContent.classList.add("hidden");
    fields.diseaseChecklistMessage.classList.remove("hidden");
    fields.diseaseChecklistMessage.classList.add("error");
    fields.diseaseChecklistMessage.innerHTML = `
      <strong>疾患確認リストを読み込めませんでした</strong>
      <span>${escapeHtml(state.diseaseChecklistsError)}</span>
    `;
    fields.exportDiseaseChecklist?.setAttribute("disabled", "");
    return;
  }
  if (!state.diseaseChecklists.length) {
    const isDiagnostic = state.selectedExam === "放射線診断専門医認定試験";
    fields.diseaseChecklistContent.classList.add("hidden");
    fields.diseaseChecklistMessage.classList.remove("hidden", "error");
    fields.diseaseChecklistMessage.innerHTML = `
      <strong>${isDiagnostic ? "疾患確認リストはまだありません" : "この試験の疾患確認リストはありません"}</strong>
      <span>${escapeHtml(examLabel(state.selectedExam))}には利用できるリストが登録されていません。</span>
    `;
    fields.exportDiseaseChecklist?.setAttribute("disabled", "");
    return;
  }

  fields.diseaseChecklistMessage.classList.add("hidden");
  fields.diseaseChecklistMessage.classList.remove("error");
  fields.diseaseChecklistContent.classList.remove("hidden");
  fields.diseaseChecklistSelect.innerHTML = state.diseaseChecklists
    .map((checklist) => {
      const selected = checklist.id === Number(state.selectedDiseaseChecklistId) ? " selected" : "";
      return `<option value="${checklist.id}"${selected}>${escapeHtml(checklist.title)}（${checklist.item_count}件）</option>`;
    })
    .join("");

  fields.diseaseStatusFilter.value = state.diseaseChecklistStatusFilter;
  fields.diseaseSearchFilter.value = state.diseaseChecklistSearchFilter;
  fields.diseaseEverWrongFilter.checked = state.diseaseChecklistEverWrongFilter;
  fields.diseaseAddedByWrongFilter.checked = state.diseaseChecklistAddedByWrongFilter;

  if (state.diseaseChecklistDetailLoading) {
    fields.diseaseChecklistSummary.innerHTML = "";
    fields.diseaseChecklistResultCount.textContent = "";
    clearDiseaseChecklistRegionNavigation();
    clearDiseaseChecklistPagination();
    fields.diseaseChecklistCards.innerHTML = `<div class="disease-checklist-message compact">疾患を読み込んでいます...</div>`;
    fields.exportDiseaseChecklist?.setAttribute("disabled", "");
    return;
  }
  if (state.diseaseChecklistDetailError) {
    fields.diseaseChecklistSummary.innerHTML = "";
    fields.diseaseChecklistResultCount.textContent = "";
    clearDiseaseChecklistRegionNavigation();
    clearDiseaseChecklistPagination();
    fields.diseaseChecklistCards.innerHTML = `
      <div class="disease-checklist-message compact error">
        <strong>疾患を読み込めませんでした</strong>
        <span>${escapeHtml(state.diseaseChecklistDetailError)}</span>
      </div>
    `;
    fields.exportDiseaseChecklist?.setAttribute("disabled", "");
    return;
  }
  if (!state.diseaseChecklistDetail) {
    fields.diseaseChecklistSummary.innerHTML = "";
    fields.diseaseChecklistResultCount.textContent = "";
    clearDiseaseChecklistRegionNavigation();
    clearDiseaseChecklistPagination();
    fields.diseaseChecklistCards.innerHTML = `<div class="disease-checklist-message compact">確認リストを選択してください。</div>`;
    fields.exportDiseaseChecklist?.setAttribute("disabled", "");
    return;
  }

  renderDiseaseChecklistSummary();
  renderDiseaseChecklistResults();
  const exportable = state.diseaseChecklistDetail.items.some((item) => ["warn", "wrong"].includes(item.status));
  fields.exportDiseaseChecklist?.toggleAttribute("disabled", !exportable);
}

async function loadDiseaseChecklist(checklistId) {
  const normalizedId = Number(checklistId);
  if (!Number.isInteger(normalizedId) || !canUseDiseaseChecklists()) return;
  const activeChecklistId = Number(
    state.diseaseChecklistDetail?.id ?? state.selectedDiseaseChecklistId,
  );
  const switchingChecklist = normalizedId !== activeChecklistId;
  const requestId = ++state.diseaseChecklistDetailRequestId;
  const contextRequestId = state.diseaseChecklistContextRequestId;
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  state.selectedDiseaseChecklistId = normalizedId;
  state.diseaseChecklistDetail = null;
  state.diseaseChecklistDetailLoading = true;
  state.diseaseChecklistDetailError = "";
  state.diseaseChecklistRecentlyReviewedItemId = null;
  if (switchingChecklist) {
    state.diseaseChecklistRegionFilter = "";
    state.diseaseChecklistPage = 1;
  }
  renderDiseaseChecklistView();
  try {
    const payload = await api(
      `/api/disease-checklists/${normalizedId}${queryFor(
        diseaseChecklistParams({}, requestedUser, requestedExam),
      )}`,
    );
    if (
      requestId !== state.diseaseChecklistDetailRequestId ||
      contextRequestId !== state.diseaseChecklistContextRequestId ||
      requestedUser !== state.currentUser ||
      requestedExam !== state.selectedExam ||
      normalizedId !== Number(state.selectedDiseaseChecklistId)
    ) {
      return;
    }
    const detail = normalizeDiseaseChecklist(payload.checklist);
    if (!detail || !Number.isInteger(detail.id)) throw new Error("疾患確認リストの形式が不正です。");
    state.diseaseChecklistDetail = detail;
    state.diseaseChecklistDetailError = "";
    replaceDiseaseChecklistSummary(detail);
  } catch (error) {
    if (
      requestId === state.diseaseChecklistDetailRequestId &&
      contextRequestId === state.diseaseChecklistContextRequestId &&
      requestedUser === state.currentUser &&
      requestedExam === state.selectedExam
    ) {
      state.diseaseChecklistDetailError = error.message;
    }
  } finally {
    if (
      requestId === state.diseaseChecklistDetailRequestId &&
      contextRequestId === state.diseaseChecklistContextRequestId &&
      requestedUser === state.currentUser &&
      requestedExam === state.selectedExam
    ) {
      state.diseaseChecklistDetailLoading = false;
      renderDiseaseChecklistView();
    }
  }
}

async function refreshDiseaseChecklists() {
  if (!canUseDiseaseChecklists() || state.diseaseChecklistsLoading) return;
  const requestId = ++state.diseaseChecklistListRequestId;
  const contextRequestId = state.diseaseChecklistContextRequestId;
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  state.diseaseChecklistsLoading = true;
  state.diseaseChecklistsError = "";
  renderDiseaseChecklistView();
  try {
    const payload = await api(
      `/api/disease-checklists${queryFor(
        diseaseChecklistParams({ includeExam: true }, requestedUser, requestedExam),
      )}`,
    );
    if (
      requestId !== state.diseaseChecklistListRequestId ||
      contextRequestId !== state.diseaseChecklistContextRequestId ||
      requestedUser !== state.currentUser ||
      requestedExam !== state.selectedExam
    ) {
      return;
    }
    state.diseaseChecklists = (payload.checklists || [])
      .map(normalizeDiseaseChecklistSummary)
      .filter((item) => Number.isInteger(item?.id));
    state.diseaseChecklistsLoaded = true;
    state.diseaseChecklistsError = "";
    const selected = diseaseChecklistById(state.selectedDiseaseChecklistId) || state.diseaseChecklists[0] || null;
    state.selectedDiseaseChecklistId = selected?.id ?? null;
    if (!selected) {
      state.diseaseChecklistDetail = null;
      state.diseaseChecklistDetailError = "";
    }
  } catch (error) {
    if (
      requestId === state.diseaseChecklistListRequestId &&
      contextRequestId === state.diseaseChecklistContextRequestId &&
      requestedUser === state.currentUser &&
      requestedExam === state.selectedExam
    ) {
      state.diseaseChecklistsError = error.message;
    }
  } finally {
    if (
      requestId === state.diseaseChecklistListRequestId &&
      contextRequestId === state.diseaseChecklistContextRequestId &&
      requestedUser === state.currentUser &&
      requestedExam === state.selectedExam
    ) {
      state.diseaseChecklistsLoading = false;
      renderDiseaseChecklistView();
      if (state.selectedDiseaseChecklistId != null && !state.diseaseChecklistsError) {
        void loadDiseaseChecklist(state.selectedDiseaseChecklistId);
      }
    }
  }
}

async function updateDiseaseChecklistItem(itemId, status) {
  const normalizedItemId = Number(itemId);
  if (
    !Number.isInteger(normalizedItemId) ||
    !DISEASE_CHECKLIST_STATUSES.has(status) ||
    !canUseDiseaseChecklists() ||
    state.diseaseChecklistUpdatingItemIds.has(normalizedItemId)
  ) {
    return;
  }
  const checklistId = Number(state.selectedDiseaseChecklistId);
  const currentItem = state.diseaseChecklistDetail?.items.find((item) => item.id === normalizedItemId);
  if (!Number.isInteger(checklistId) || !currentItem || currentItem.status === status) return;
  const contextRequestId = state.diseaseChecklistContextRequestId;
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  state.diseaseChecklistUpdatingItemIds.add(normalizedItemId);
  renderDiseaseChecklistCards();
  try {
    const payload = await api(`/api/disease-checklists/${checklistId}/items/${normalizedItemId}`, {
      method: "PUT",
      body: JSON.stringify({ status, user_name: requestedUser }),
    });
    if (
      contextRequestId !== state.diseaseChecklistContextRequestId ||
      requestedUser !== state.currentUser ||
      requestedExam !== state.selectedExam ||
      checklistId !== Number(state.selectedDiseaseChecklistId)
    ) {
      return;
    }
    const updatedItem = normalizeDiseaseChecklistItem(payload.item);
    if (!updatedItem || updatedItem.id !== normalizedItemId) {
      throw new Error("評価結果の形式が不正です。");
    }
    state.diseaseChecklistDetail.items = state.diseaseChecklistDetail.items.map((item) =>
      item.id === normalizedItemId ? updatedItem : item,
    );
    state.diseaseChecklistRecentlyReviewedItemId = normalizedItemId;
    if (payload.checklist) {
      replaceDiseaseChecklistSummary(payload.checklist);
    } else {
      const counts = diseaseChecklistCounts(state.diseaseChecklistDetail.items);
      replaceDiseaseChecklistSummary({
        ...state.diseaseChecklistDetail,
        item_count: state.diseaseChecklistDetail.items.length,
        status_counts: counts,
      });
    }
    toast(`${updatedItem.disease_name}を「${diseaseChecklistStatusMeta(status).text}」に更新しました。`);
  } catch (error) {
    if (
      contextRequestId === state.diseaseChecklistContextRequestId &&
      requestedUser === state.currentUser &&
      requestedExam === state.selectedExam
    ) {
      toast(error.message);
    }
  } finally {
    if (contextRequestId === state.diseaseChecklistContextRequestId) {
      state.diseaseChecklistUpdatingItemIds.delete(normalizedItemId);
      renderDiseaseChecklistView();
    }
  }
}

function safeTsvCell(value) {
  let text = String(value ?? "").replace(/\r\n?/g, "\n");
  if (/^[\t\n ]*[=+\-@]/.test(text)) text = `'${text}`;
  return /[\t\n"]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function exportDiseaseChecklistTsv() {
  const detail = state.diseaseChecklistDetail;
  if (!detail) return;
  const items = detail.items.filter((item) => ["warn", "wrong"].includes(item.status));
  if (!items.length) {
    toast("TSVに出力する△または×の疾患はありません。");
    return;
  }
  const header = ["疾患名", "領域", "評価", "誤答経験", "画像所見メモ", "出典", "更新日時"];
  const rows = items.map((item) => [
    item.disease_name,
    item.primary_region,
    diseaseChecklistStatusMeta(item.status).label,
    item.ever_wrong ? "あり" : "なし",
    item.review_note,
    item.sources.map(diseaseSourceText).filter(Boolean).join(" | "),
    item.status_updated_at || item.reviewed_at || item.first_reviewed_at || "",
  ]);
  const tsv = `\uFEFF${[header, ...rows].map((row) => row.map(safeTsvCell).join("\t")).join("\r\n")}\r\n`;
  const blob = new Blob([tsv], { type: "text/tab-separated-values;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const date = new Date().toISOString().slice(0, 10).replaceAll("-", "");
  const title = `${examLabel(detail.exam || state.selectedExam)}-${detail.title}`
    .replace(/[\\/:*?"<>|\s]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${title || "disease-checklist"}-${date}.tsv`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function refreshPracticeSession() {
  const requestId = ++state.practiceSessionRequestId;
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  const payload = await api(`/api/practice-session${queryFor(practiceSessionParams(requestedUser, requestedExam))}`);
  if (
    requestId !== state.practiceSessionRequestId ||
    requestedUser !== state.currentUser ||
    requestedExam !== state.selectedExam
  ) {
    return null;
  }
  state.practiceSession = normalizePracticeSession(payload.practice_session);
  renderPracticeSessionCard();
  return state.practiceSession;
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
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  const query = selectedFilters();
  const statsParams = userScopedParams();
  if (state.selectedExam) statsParams.set("exam", state.selectedExam);
  const summaryParams = userScopedParams();
  if (state.selectedExam) summaryParams.set("exam", state.selectedExam);
  const shouldLoadQuestions =
    forceLoadQuestions || !state.showStudyMap || state.activeTab === "library" || hasActiveQuestionFilter();
  const [stats, summaryPayload, questionPayload, practiceSessionPayload] = await Promise.all([
    api(`/api/stats${queryFor(statsParams)}`),
    api(`/api/study-summary${queryFor(summaryParams)}`),
    shouldLoadQuestions ? api(`/api/questions${query ? `?${query}` : ""}`) : Promise.resolve(null),
    api(`/api/practice-session${queryFor(practiceSessionParams(requestedUser, requestedExam))}`),
    state.activeTab === "history" ? refreshHistory() : Promise.resolve(),
  ]);
  if (requestId !== state.refreshRequestId) return;

  state.stats = stats;
  state.studySummary = summaryPayload;
  state.practiceSessionRequestId += 1;
  const refreshedPracticeSession = normalizePracticeSession(practiceSessionPayload.practice_session);
  if (
    hasActivePracticeSession() &&
    state.practiceSession?.token !== refreshedPracticeSession?.token
  ) {
    state.practiceSessionActive = false;
  }
  state.practiceSession = refreshedPracticeSession;
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
  const canUseDiseaseChecklist = canUseDiseaseChecklists();
  fields.diseaseChecklistTab?.classList.toggle("hidden", !canUseDiseaseChecklist);
  if (!canManage && state.activeTab === "users") {
    activateTab("practice");
  }
  if (!canUseDiseaseChecklist && state.activeTab === "diseaseChecklist") {
    clearDiseaseChecklistState();
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
  state.practiceSession = null;
  state.practiceSessionActive = false;
  state.practiceFlowRequestId += 1;
  clearQuestionSetState();
  clearDiseaseChecklistState();
  setPracticeStarting(false);
  state.practiceSessionRequestId += 1;
  state.showStudyMap = true;
  try {
    window.localStorage.setItem(USER_STORAGE_KEY, nextUser);
  } catch {
    // 履歴自体はサーバー側に残るので、端末保存に失敗しても演習は継続できます。
  }
  toast(`${nextUser} の履歴に切り替えました。`);
  refreshAll({ keepQuestion: false }).catch((error) => toast(error.message));
  if (state.activeTab === "diseaseChecklist") void refreshDiseaseChecklists();
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

function practiceSessionFilterLabels(filters = {}) {
  const labels = [];
  if (filters.year) labels.push(`${filters.year}年`);
  if (filters.category) labels.push(filters.category);
  if (filters.q) labels.push(`検索: ${filters.q}`);
  const resultMarks = Array.isArray(filters.result_marks) ? new Set(filters.result_marks) : null;
  const resultLabels = resultFilterLabels(resultMarks);
  if (resultLabels.length) labels.push(resultLabels.join("・"));
  const localFilter = filters.local_filter || {};
  if (localFilter.hasImages) labels.push("画像あり");
  if (localFilter.unattempted) labels.push("未演習");
  if (localFilter.withoutAnswer) labels.push("解答未登録");
  return labels;
}

function renderPracticeSessionCard() {
  if (!fields.practiceSessionCard) return;
  const session = state.practiceSession;
  if (!session?.token) {
    fields.practiceSessionCard.classList.add("hidden");
    fields.practiceSessionCard.innerHTML = "";
    return;
  }

  const total = Math.max(0, Number(session.total || 0));
  const completed = Math.min(total, Math.max(0, Number(session.completed || 0)));
  const remaining = Math.max(0, Number(session.remaining ?? total - completed));
  const isComplete = session.status === "completed" || remaining === 0;
  const conditionLabels = practiceSessionFilterLabels(session.filters);
  const action = isComplete ? "restart-practice-session" : "resume-practice-session";
  const actionLabel = isComplete ? "現在の条件でもう一周" : "続きから";

  fields.practiceSessionCard.classList.remove("hidden");
  fields.practiceSessionCard.innerHTML = `
    <div class="practice-session-card-copy">
      <span class="practice-session-card-kicker">保存中のクイックランダム</span>
      <strong>${isComplete ? "一周完了" : `${completed}/${total}問 完了`}</strong>
      <span>${conditionLabels.length ? escapeHtml(conditionLabels.join(" / ")) : "全問題"}</span>
    </div>
    <div class="practice-session-card-progress">
      <progress value="${completed}" max="${Math.max(1, total)}" aria-label="${completed}/${total}問 完了"></progress>
      <span>${isComplete ? "全問完了" : `残り${remaining}問`}</span>
    </div>
    <div class="practice-session-card-actions">
      <button class="primary" type="button" data-${action}>${actionLabel}</button>
      <button class="ghost small" type="button" data-discard-practice-session>破棄</button>
    </div>
  `;
}

function questionSetRoundStatusLabel(status) {
  if (status === "completed") return "完了";
  if (status === "abandoned") return "中断";
  return "進行中";
}

function formatQuestionSetDate(value) {
  if (!value) return "日時不明";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "日時不明" : date.toLocaleString("ja-JP");
}

function questionSetRoundDate(round) {
  return formatQuestionSetDate(
    round?.completed_at || round?.abandoned_at || round?.updated_at || round?.created_at,
  );
}

function questionSetRoundMarks(round) {
  const marks = round?.self_marks || {};
  return `○${Number(marks.ok || 0)} △${Number(marks.warn || 0)} ×${Number(marks.wrong || 0)}`;
}

function renderQuestionSetCards() {
  if (!fields.questionSetCards) return;
  if (state.questionSetsLoading && !state.questionSetsLoaded) {
    fields.questionSetCards.innerHTML = `<div class="question-set-message">問題セットを読み込んでいます...</div>`;
    return;
  }
  if (state.questionSetsError && !state.questionSetsLoaded) {
    fields.questionSetCards.innerHTML = `
      <div class="question-set-message error">
        <strong>問題セットを読み込めませんでした</strong>
        <span>${escapeHtml(state.questionSetsError)}</span>
      </div>
    `;
    return;
  }
  if (!state.questionSets.length) {
    fields.questionSetCards.innerHTML = `
      <div class="question-set-message">
        <strong>この試験の問題セットはありません</strong>
        <span>Codexでセットを作成すると、ここからランダム演習を開始できます。</span>
      </div>
    `;
    return;
  }

  fields.questionSetCards.innerHTML = state.questionSets
    .map((questionSet) => {
      const activeRound = questionSet.active_round;
      const latestRound = questionSet.latest_round;
      const displayRound = activeRound || latestRound;
      const total = Math.max(0, Number(questionSet.total || displayRound?.total || 0));
      const completed = Math.min(total, Math.max(0, Number(displayRound?.completed || 0)));
      const remaining = Math.max(0, Number(displayRound?.remaining ?? total - completed));
      const isCompleted = !activeRound && latestRound?.status === "completed";
      const primaryAction = activeRound
        ? `<button class="primary" type="button" data-question-set-resume="${questionSet.id}">続きから</button>`
        : `<button class="primary" type="button" data-question-set-start="${questionSet.id}">${isCompleted ? "再シャッフルしてもう一周" : "ランダムに始める"}</button>`;
      const activeActions = activeRound
        ? `
          <button class="ghost" type="button" data-question-set-restart="${questionSet.id}">最初からやり直す</button>
          <button class="ghost" type="button" data-question-set-abandon="${questionSet.id}" data-round-id="${activeRound.id}">中断して保存</button>
        `
        : "";
      const roundLabel = activeRound
        ? `第${activeRound.round_number}周・進行中`
        : latestRound
          ? `第${latestRound.round_number}周・${questionSetRoundStatusLabel(latestRound.status)}`
          : "未開始";
      const progressText = activeRound
        ? `${completed}/${total}問 完了・残り${remaining}問`
        : latestRound
          ? `${completed}/${total}問 実施・${questionSetRoundMarks(latestRound)}`
          : `${total}問`;

      return `
        <article class="question-set-card" data-question-set-id="${questionSet.id}">
          <div class="question-set-card-head">
            <div class="question-set-card-title-wrap">
              <span class="question-set-card-kicker">${escapeHtml(roundLabel)}</span>
              <h3>${escapeHtml(questionSet.title)}</h3>
            </div>
            <span class="count-pill">${total}問</span>
          </div>
          <div class="question-set-card-progress">
            <progress value="${completed}" max="${Math.max(1, total)}" aria-label="${completed}/${total}問 完了"></progress>
            <span>${escapeHtml(progressText)}</span>
          </div>
          <div class="question-set-card-actions">
            ${primaryAction}
            ${activeActions}
            <button class="ghost" type="button" data-question-set-history="${questionSet.id}">周回履歴</button>
          </div>
          <div class="question-set-card-danger">
            <button class="danger small" type="button" data-question-set-delete="${questionSet.id}">セットを削除</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderQuestionSetRoundList() {
  if (!fields.questionSetRoundList) return;
  const questionSet = questionSetById(state.selectedQuestionSetId);
  if (fields.questionSetHistoryTitle) {
    fields.questionSetHistoryTitle.textContent = questionSet?.title || "問題セット";
  }
  if (!state.questionSetRounds.length) {
    fields.questionSetRoundList.innerHTML = `<div class="question-set-message">保存された周回履歴はありません。</div>`;
  } else {
    fields.questionSetRoundList.innerHTML = state.questionSetRounds
      .map((round) => {
        const status = questionSetRoundStatusLabel(round.status);
        const rate = round.graded ? `${round.rate}%` : "-";
        const activeActions = round.status === "active"
          ? `
            <button class="primary" type="button" data-question-set-resume="${state.selectedQuestionSetId}">続きから</button>
            <button class="ghost" type="button" data-question-set-abandon="${state.selectedQuestionSetId}" data-round-id="${round.id}">中断して保存</button>
          `
          : `
            <button class="danger small" type="button" data-question-set-round-delete="${round.id}">この周回を削除</button>
          `;
        return `
          <article class="question-set-round-card ${escapeHtml(round.status)}">
            <div class="question-set-round-card-head">
              <strong>第${round.round_number}周</strong>
              <span class="round-status ${escapeHtml(round.status)}">${status}</span>
            </div>
            <time>${escapeHtml(questionSetRoundDate(round))}</time>
            <div class="question-set-round-metrics">
              <span><strong>${round.completed}/${round.total}</strong>問 実施</span>
              <span>正答率 <strong>${escapeHtml(rate)}</strong></span>
              <span>${escapeHtml(questionSetRoundMarks(round))}</span>
              ${round.unavailable ? `<span>利用不可 ${round.unavailable}問</span>` : ""}
            </div>
            <div class="question-set-round-actions">
              <button class="ghost" type="button" data-question-set-round-detail="${round.id}">問題別結果</button>
              ${activeActions}
            </div>
          </article>
        `;
      })
      .join("");
  }

  const pageCount = Math.max(1, Math.ceil(state.questionSetRoundsTotal / QUESTION_SET_ROUND_PAGE_SIZE));
  const page = Math.floor(state.questionSetRoundsOffset / QUESTION_SET_ROUND_PAGE_SIZE) + 1;
  fields.questionSetRoundPagination?.classList.toggle(
    "hidden",
    state.questionSetRoundsTotal <= QUESTION_SET_ROUND_PAGE_SIZE,
  );
  if (fields.questionSetRoundPageStatus) fields.questionSetRoundPageStatus.textContent = `${page} / ${pageCount}`;
  if (fields.questionSetRoundPrev) fields.questionSetRoundPrev.disabled = state.questionSetRoundsOffset <= 0;
  if (fields.questionSetRoundNext) {
    fields.questionSetRoundNext.disabled =
      state.questionSetRoundsOffset + QUESTION_SET_ROUND_PAGE_SIZE >= state.questionSetRoundsTotal;
  }
}

function questionSetItemResult(item) {
  if (item?.available === false) {
    return { className: "pending", label: "利用不可" };
  }
  const value = item?.is_correct;
  if (value === true || value === 1 || value === "1") {
    return { className: "ok", label: "正解" };
  }
  if (value === false || value === 0 || value === "0") {
    return { className: "ng", label: "不正解" };
  }
  return { className: "pending", label: "未採点" };
}

function renderQuestionSetRoundDetail() {
  if (!fields.questionSetRoundItems) return;
  const questionSet = questionSetById(state.selectedQuestionSetId);
  const round = state.questionSetRoundDetail;
  if (fields.questionSetRoundDetailTitle) {
    fields.questionSetRoundDetailTitle.textContent = round
      ? `${questionSet?.title || "問題セット"}・第${round.round_number}周`
      : questionSet?.title || "周回";
  }
  if (fields.questionSetRoundDetailSummary) {
    fields.questionSetRoundDetailSummary.innerHTML = round
      ? `
        <span class="round-status ${escapeHtml(round.status)}">${questionSetRoundStatusLabel(round.status)}</span>
        <span>${round.completed}/${round.total}問 実施</span>
        <span>正答率 ${round.graded ? `${round.rate}%` : "-"}</span>
        <span>${escapeHtml(questionSetRoundMarks(round))}</span>
      `
      : "";
  }

  if (!state.questionSetRoundItems.length) {
    fields.questionSetRoundItems.innerHTML = `<div class="question-set-message">このページに表示できる問題別結果はありません。</div>`;
  } else {
    fields.questionSetRoundItems.innerHTML = state.questionSetRoundItems
      .map((item) => {
        const result = questionSetItemResult(item);
        const selfMark = SELF_MARKS[item.self_mark];
        return `
          <article class="question-set-round-item">
            <div class="question-set-round-item-position">${Number(item.position || 0)}</div>
            <div class="question-set-round-item-meta">
              <strong>${escapeHtml(item.year || "年度不明")}・問${escapeHtml(item.question_number ?? "-")}</strong>
              <span>${escapeHtml(item.category || "分野不明")}</span>
            </div>
            <dl class="question-set-round-item-answers">
              <div><dt>解答</dt><dd>${escapeHtml(item.user_answer || "-")}</dd></div>
              <div><dt>正答</dt><dd>${escapeHtml(item.correct_answer || "-")}</dd></div>
            </dl>
            <div class="question-set-round-item-result">
              <span class="result-mark ${result.className}">${result.label}</span>
              <span>${selfMark ? `${selfMark.label} ${selfMark.text}` : "自己評価なし"}</span>
            </div>
          </article>
        `;
      })
      .join("");
  }

  const pageCount = Math.max(1, Math.ceil(state.questionSetRoundItemsTotal / QUESTION_SET_ROUND_ITEM_PAGE_SIZE));
  const page = Math.floor(state.questionSetRoundItemsOffset / QUESTION_SET_ROUND_ITEM_PAGE_SIZE) + 1;
  fields.questionSetRoundItemPagination?.classList.toggle(
    "hidden",
    state.questionSetRoundItemsTotal <= QUESTION_SET_ROUND_ITEM_PAGE_SIZE,
  );
  if (fields.questionSetRoundItemPageStatus) fields.questionSetRoundItemPageStatus.textContent = `${page} / ${pageCount}`;
  if (fields.questionSetRoundItemPrev) fields.questionSetRoundItemPrev.disabled = state.questionSetRoundItemsOffset <= 0;
  if (fields.questionSetRoundItemNext) {
    fields.questionSetRoundItemNext.disabled =
      state.questionSetRoundItemsOffset + QUESTION_SET_ROUND_ITEM_PAGE_SIZE >= state.questionSetRoundItemsTotal;
  }
}

function renderQuestionSetPanel() {
  const isQuestionSetMode = state.studyMode === "sets";
  fields.practiceResultFilter?.classList.toggle("hidden", isQuestionSetMode);
  fields.startAllRandom?.classList.toggle("hidden", isQuestionSetMode);
  fields.studyList?.classList.toggle("hidden", isQuestionSetMode);
  fields.questionSetPanel?.classList.toggle("hidden", !isQuestionSetMode);
  if (!isQuestionSetMode) return;

  fields.questionSetPanel?.toggleAttribute("aria-busy", state.questionSetsLoading || state.practiceStarting);
  if (fields.refreshQuestionSets) {
    fields.refreshQuestionSets.disabled = state.questionSetsLoading || state.practiceStarting;
  }

  fields.questionSetListView?.classList.toggle("hidden", state.questionSetView !== "list");
  fields.questionSetHistoryView?.classList.toggle("hidden", state.questionSetView !== "history");
  fields.questionSetRoundDetailView?.classList.toggle("hidden", state.questionSetView !== "detail");
  if (state.questionSetView === "list") renderQuestionSetCards();
  if (state.questionSetView === "history") renderQuestionSetRoundList();
  if (state.questionSetView === "detail") renderQuestionSetRoundDetail();
}

function clearQuestionSetState() {
  state.questionSetRequestId += 1;
  state.questionSetHistoryRequestId += 1;
  state.questionSetDetailRequestId += 1;
  state.questionSetFlowRequestId += 1;
  state.questionSets = [];
  state.questionSetsLoaded = false;
  state.questionSetsLoading = false;
  state.questionSetsError = "";
  state.questionSetView = "list";
  state.selectedQuestionSetId = null;
  state.questionSetRounds = [];
  state.questionSetRoundsTotal = 0;
  state.questionSetRoundsOffset = 0;
  state.selectedQuestionSetRoundId = null;
  state.questionSetRoundDetail = null;
  state.questionSetRoundItems = [];
  state.questionSetRoundItemsTotal = 0;
  state.questionSetRoundItemsOffset = 0;
  state.questionSetPractice = null;
  state.questionSetPracticeActive = false;
}

function upsertQuestionSet(value) {
  if (!value || typeof value !== "object") return null;
  const id = Number(value.id);
  const index = state.questionSets.findIndex((item) => item.id === id);
  const current = index >= 0 ? state.questionSets[index] : null;
  const normalized = normalizeQuestionSet({ ...(current || {}), ...value });
  if (!normalized || !Number.isInteger(normalized.id)) return null;
  if (index >= 0) {
    state.questionSets[index] = normalized;
  } else {
    state.questionSets.push(normalized);
  }
  return normalized;
}

function syncQuestionSetRoundInList(roundValue, questionSetValue = null) {
  const practiceSet = questionSetValue || state.questionSetPractice?.question_set;
  const questionSet = practiceSet ? upsertQuestionSet(practiceSet) : null;
  const setId = Number(questionSet?.id || state.questionSetPractice?.question_set?.id);
  const current = questionSetById(setId);
  if (!current) return;
  const previousRound =
    current.active_round?.id === Number(roundValue?.id)
      ? current.active_round
      : current.latest_round?.id === Number(roundValue?.id)
        ? current.latest_round
        : null;
  const round = normalizeQuestionSetRound(roundValue, previousRound);
  if (!round) return;
  current.active_round = round.status === "active" ? round : null;
  current.latest_round = round;
  current.rounds_count = Math.max(Number(current.rounds_count || 0), Number(round.round_number || 0));
  current.updated_at = round.updated_at || current.updated_at;
}

async function refreshQuestionSets({ force = false } = {}) {
  if (state.questionSetsLoading && !force) return;
  const requestId = ++state.questionSetRequestId;
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  state.questionSetsLoading = true;
  state.questionSetsError = "";
  renderQuestionSetPanel();
  try {
    const payload = await api(
      `/api/question-sets${queryFor(questionSetParams({}, requestedUser, requestedExam))}`,
    );
    if (
      requestId !== state.questionSetRequestId ||
      requestedUser !== state.currentUser ||
      requestedExam !== state.selectedExam
    ) {
      return;
    }
    state.questionSets = (Array.isArray(payload.question_sets) ? payload.question_sets : [])
      .map(normalizeQuestionSet)
      .filter((item) => item && Number.isInteger(item.id))
      .sort((left, right) => {
        const leftTime = new Date(left.updated_at || left.created_at || 0).getTime() || 0;
        const rightTime = new Date(right.updated_at || right.created_at || 0).getTime() || 0;
        return rightTime - leftTime || right.id - left.id;
      });
      state.questionSetsLoaded = true;
    if (state.selectedQuestionSetId && !questionSetById(state.selectedQuestionSetId)) {
      state.questionSetView = "list";
      state.selectedQuestionSetId = null;
    }
  } catch (error) {
    if (
      requestId === state.questionSetRequestId &&
      requestedUser === state.currentUser &&
      requestedExam === state.selectedExam
    ) {
      state.questionSetsError = error.message;
      toast(error.message);
    }
  } finally {
    if (requestId === state.questionSetRequestId) {
      state.questionSetsLoading = false;
      renderQuestionSetPanel();
    }
  }
}

async function openQuestionSetHistory(setId, offset = 0) {
  const normalizedSetId = Number(setId);
  if (!Number.isInteger(normalizedSetId)) return;
  const requestId = ++state.questionSetHistoryRequestId;
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  const normalizedOffset = Math.max(0, Number(offset) || 0);
  state.selectedQuestionSetId = normalizedSetId;
  state.questionSetView = "history";
  state.questionSetRoundsOffset = normalizedOffset;
  state.questionSetRounds = [];
  renderQuestionSetPanel();
  fields.questionSetRoundList.innerHTML = `<div class="question-set-message">周回履歴を読み込んでいます...</div>`;
  try {
    const params = questionSetParams(
      { limit: String(QUESTION_SET_ROUND_PAGE_SIZE), offset: String(normalizedOffset) },
      requestedUser,
      requestedExam,
    );
    const payload = await api(`/api/question-sets/${normalizedSetId}/rounds${queryFor(params)}`);
    if (
      requestId !== state.questionSetHistoryRequestId ||
      requestedUser !== state.currentUser ||
      requestedExam !== state.selectedExam ||
      state.selectedQuestionSetId !== normalizedSetId
    ) {
      return;
    }
    state.questionSetRounds = (Array.isArray(payload.rounds) ? payload.rounds : [])
      .map((round) => normalizeQuestionSetRound(round))
      .filter(Boolean);
    state.questionSetRoundsTotal = Math.max(0, Number(payload.total || 0));
    state.questionSetRoundsOffset = Math.max(0, Number(payload.offset ?? normalizedOffset));
    renderQuestionSetPanel();
  } catch (error) {
    if (
      requestId === state.questionSetHistoryRequestId &&
      requestedUser === state.currentUser &&
      requestedExam === state.selectedExam
    ) {
      fields.questionSetRoundList.innerHTML = `<div class="question-set-message error">${escapeHtml(error.message)}</div>`;
      toast(error.message);
    }
  }
}

async function openQuestionSetRoundDetail(setId, roundId, offset = 0) {
  const normalizedSetId = Number(setId);
  const normalizedRoundId = Number(roundId);
  if (!Number.isInteger(normalizedSetId) || !Number.isInteger(normalizedRoundId)) return;
  const requestId = ++state.questionSetDetailRequestId;
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  const normalizedOffset = Math.max(0, Number(offset) || 0);
  state.selectedQuestionSetId = normalizedSetId;
  state.selectedQuestionSetRoundId = normalizedRoundId;
  state.questionSetView = "detail";
  state.questionSetRoundItemsOffset = normalizedOffset;
  state.questionSetRoundDetail = null;
  state.questionSetRoundItems = [];
  renderQuestionSetPanel();
  fields.questionSetRoundItems.innerHTML = `<div class="question-set-message">問題別結果を読み込んでいます...</div>`;
  try {
    const params = questionSetParams(
      { limit: String(QUESTION_SET_ROUND_ITEM_PAGE_SIZE), offset: String(normalizedOffset) },
      requestedUser,
      requestedExam,
    );
    const payload = await api(
      `/api/question-sets/${normalizedSetId}/rounds/${normalizedRoundId}${queryFor(params)}`,
    );
    if (
      requestId !== state.questionSetDetailRequestId ||
      requestedUser !== state.currentUser ||
      requestedExam !== state.selectedExam ||
      state.selectedQuestionSetId !== normalizedSetId ||
      state.selectedQuestionSetRoundId !== normalizedRoundId
    ) {
      return;
    }
    state.questionSetRoundDetail = normalizeQuestionSetRound(payload.round);
    state.questionSetRoundItems = Array.isArray(payload.items)
      ? payload.items
      : Array.isArray(payload.round?.items)
        ? payload.round.items
        : [];
    state.questionSetRoundItemsTotal = Math.max(
      0,
      Number(payload.total ?? payload.round?.items_total ?? state.questionSetRoundItems.length),
    );
    state.questionSetRoundItemsOffset = Math.max(0, Number(payload.offset ?? normalizedOffset));
    renderQuestionSetPanel();
  } catch (error) {
    if (
      requestId === state.questionSetDetailRequestId &&
      requestedUser === state.currentUser &&
      requestedExam === state.selectedExam
    ) {
      fields.questionSetRoundItems.innerHTML = `<div class="question-set-message error">${escapeHtml(error.message)}</div>`;
      toast(error.message);
    }
  }
}

function showQuestionSetList() {
  state.questionSetHistoryRequestId += 1;
  state.questionSetDetailRequestId += 1;
  state.questionSetView = "list";
  state.selectedQuestionSetId = null;
  state.selectedQuestionSetRoundId = null;
  renderQuestionSetPanel();
}

function showQuestionSetHistoryFromDetail() {
  state.questionSetDetailRequestId += 1;
  state.questionSetView = "history";
  state.selectedQuestionSetRoundId = null;
  renderQuestionSetPanel();
}

async function openQuestionSetRoundForPractice(setId, { action = "resume" } = {}) {
  if (state.practiceStarting) return;
  const normalizedSetId = Number(setId);
  if (!Number.isInteger(normalizedSetId)) return;
  const flowRequestId = ++state.questionSetFlowRequestId;
  const requestId = ++state.refreshRequestId;
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  const questionSet = questionSetById(normalizedSetId) || {
    id: normalizedSetId,
    title: "問題セット",
    exam: requestedExam,
  };
  setPracticeStarting(true);
  try {
    if (action === "start" || action === "restart") {
      const suffix = action === "restart" ? "/rounds/restart" : "/rounds";
      const mutationPayload = await api(
        `/api/question-sets/${normalizedSetId}${suffix}${queryFor(questionSetParams({}, requestedUser, requestedExam))}`,
        { method: "POST", body: JSON.stringify({}) },
      );
      if (mutationPayload.question_set) upsertQuestionSet(mutationPayload.question_set);
    }

    const questionParams = userScopedParams();
    questionParams.set("exam", questionSet.exam || requestedExam);
    const [activePayload, questionPayload] = await Promise.all([
      api(
        `/api/question-sets/${normalizedSetId}/rounds/active${queryFor(questionSetParams({}, requestedUser, requestedExam))}`,
      ),
      api(`/api/questions${queryFor(questionParams)}`),
    ]);
    if (
      flowRequestId !== state.questionSetFlowRequestId ||
      requestId !== state.refreshRequestId ||
      requestedUser !== state.currentUser ||
      requestedExam !== state.selectedExam
    ) {
      return;
    }

    const activeSet = normalizeQuestionSet(activePayload.question_set) || normalizeQuestionSet(questionSet);
    const round = normalizeQuestionSetRound(activePayload.round);
    if (!round?.token || round.status !== "active") {
      throw new Error("進行中の周回を取得できませんでした。");
    }
    state.practiceSessionActive = false;
    clearStudyFilters();
    state.questionSetPractice = { question_set: activeSet, round };
    state.questionSetPracticeActive = true;
    state.allQuestions = questionPayload.questions || [];
    state.studyQuestions = state.allQuestions;
    state.questions = filteredPracticeQuestions();
    state.questionsLoaded = true;
    state.libraryPage = 1;
    state.showStudyMap = false;
    syncQuestionSetRoundInList(round, activeSet);
    renderFilterSummary();
    renderPracticeSessionCard();
    renderQuestionTable();
    const nextId = Number(round.next_question_id);
    const nextIndex = Number.isInteger(nextId)
      ? state.questions.findIndex((question) => Number(question.id) === nextId)
      : -1;
    setCurrentQuestionByIndex(nextIndex >= 0 ? nextIndex : 0);
  } catch (error) {
    toast(error.message);
  } finally {
    if (flowRequestId === state.questionSetFlowRequestId) setPracticeStarting(false);
  }
}

function startQuestionSetRound(setId) {
  void openQuestionSetRoundForPractice(setId, { action: "start" });
}

function restartQuestionSetRound(setId) {
  const questionSet = questionSetById(setId) || state.questionSetPractice?.question_set;
  const activeRound = questionSet?.active_round || state.questionSetPractice?.round;
  if (!activeRound || activeRound.status !== "active") {
    startQuestionSetRound(setId);
    return;
  }
  const message = `「${questionSet.title}」第${activeRound.round_number}周を中断として保存し、問題順を変えて新しい周回を始めます。解答済みの結果は周回履歴に残ります。よろしいですか？`;
  if (!window.confirm(message)) return;
  void openQuestionSetRoundForPractice(setId, { action: "restart" });
}

async function abandonQuestionSetRound(setId, roundId) {
  if (state.practiceStarting) return;
  const normalizedSetId = Number(setId);
  const normalizedRoundId = Number(roundId);
  if (!Number.isInteger(normalizedSetId) || !Number.isInteger(normalizedRoundId)) return;
  const questionSet = questionSetById(normalizedSetId) || state.questionSetPractice?.question_set;
  const round = questionSet?.active_round || state.questionSetPractice?.round;
  const title = questionSet?.title || "この問題セット";
  const roundNumber = round?.round_number || "現在の";
  if (
    !window.confirm(
      `「${title}」第${roundNumber}周を中断として保存します。解答済みの結果は周回履歴に残り、この周回は再開できなくなります。よろしいですか？`,
    )
  ) {
    return;
  }
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  const flowRequestId = ++state.questionSetFlowRequestId;
  setPracticeStarting(true);
  try {
    await api(
      `/api/question-sets/${normalizedSetId}/rounds/${normalizedRoundId}/abandon${queryFor(questionSetParams({}, requestedUser, requestedExam))}`,
      { method: "POST", body: JSON.stringify({}) },
    );
    if (
      flowRequestId !== state.questionSetFlowRequestId ||
      requestedUser !== state.currentUser ||
      requestedExam !== state.selectedExam
    ) {
      return;
    }
    if (
      state.questionSetPractice?.question_set?.id === normalizedSetId &&
      state.questionSetPractice?.round?.id === normalizedRoundId
    ) {
      state.questionSetPracticeActive = false;
      state.questionSetPractice = null;
    }
    toast("周回を中断として保存しました。");
    await refreshQuestionSets({ force: true });
    if (state.questionSetView === "history" && state.selectedQuestionSetId === normalizedSetId) {
      await openQuestionSetHistory(normalizedSetId, state.questionSetRoundsOffset);
    }
  } catch (error) {
    toast(error.message);
  } finally {
    if (flowRequestId === state.questionSetFlowRequestId) setPracticeStarting(false);
  }
}

async function deleteQuestionSetRound(roundId) {
  const setId = Number(state.selectedQuestionSetId);
  const normalizedRoundId = Number(roundId);
  if (!Number.isInteger(setId) || !Number.isInteger(normalizedRoundId)) return;
  const round = state.questionSetRounds.find((item) => item.id === normalizedRoundId);
  const questionSet = questionSetById(setId);
  if (!round || round.status === "active") return;
  if (
    !window.confirm(
      `「${questionSet?.title || "問題セット"}」第${round.round_number}周（${questionSetRoundStatusLabel(round.status)}・${round.completed}/${round.total}問）の周回履歴だけを削除します。問題セットと通常の解答履歴は残ります。よろしいですか？`,
    )
  ) {
    return;
  }
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  try {
    await api(
      `/api/question-sets/${setId}/rounds/${normalizedRoundId}${queryFor(questionSetParams({}, requestedUser, requestedExam))}`,
      { method: "DELETE" },
    );
    if (requestedUser !== state.currentUser || requestedExam !== state.selectedExam) return;
    toast("周回履歴を削除しました。");
    await refreshQuestionSets({ force: true });
    const nextOffset =
      state.questionSetRounds.length === 1 && state.questionSetRoundsOffset > 0
        ? Math.max(0, state.questionSetRoundsOffset - QUESTION_SET_ROUND_PAGE_SIZE)
        : state.questionSetRoundsOffset;
    await openQuestionSetHistory(setId, nextOffset);
  } catch (error) {
    toast(error.message);
  }
}

async function deleteQuestionSet(setId) {
  const normalizedSetId = Number(setId);
  if (!Number.isInteger(normalizedSetId)) return;
  const questionSet = questionSetById(normalizedSetId);
  if (!questionSet) return;
  if (
    !window.confirm(
      `「${questionSet.title}」と、その全周回履歴を削除します。元の問題と通常の解答履歴は削除されません。よろしいですか？`,
    )
  ) {
    return;
  }
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  try {
    await api(
      `/api/question-sets/${normalizedSetId}${queryFor(questionSetParams({}, requestedUser, requestedExam))}`,
      { method: "DELETE" },
    );
    if (requestedUser !== state.currentUser || requestedExam !== state.selectedExam) return;
    if (state.questionSetPractice?.question_set?.id === normalizedSetId) {
      state.questionSetPractice = null;
      state.questionSetPracticeActive = false;
    }
    showQuestionSetList();
    toast("問題セットと全周回履歴を削除しました。");
    await refreshQuestionSets({ force: true });
  } catch (error) {
    toast(error.message);
  }
}

function renderStudyMap() {
  if (!fields.studyList) return;
  renderPracticeSessionCard();
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
  renderQuestionSetPanel();
  if (state.studyMode === "sets" && !state.questionSetsLoaded && !state.questionSetsLoading) {
    void refreshQuestionSets();
  }
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
  fields.backToStudyMap.textContent = hasQuestionSetPracticeContext() ? "問題セット一覧へ" : "一覧へ戻る";
  updateFilterPanelOpen();
  document.body.classList.remove("study-map-active");
  document.body.classList.toggle("practice-session-active", state.activeTab === "practice");
}

function setPracticeStarting(value) {
  state.practiceStarting = value;
  fields.studyMap?.toggleAttribute("aria-busy", value);
  fields.startAllRandom.disabled = value;
  if (fields.refreshQuestionSets) fields.refreshQuestionSets.disabled = value;
  fields.studyList?.querySelectorAll("button").forEach((button) => {
    button.disabled = value;
  });
  fields.practiceSessionCard?.querySelectorAll("button").forEach((button) => {
    button.disabled = value;
  });
  fields.questionSetPanel?.querySelectorAll("button").forEach((button) => {
    button.disabled = value;
  });
  if (!value) renderQuestionSetPanel();
}

function shuffledQuestionIds(questions) {
  const ids = questions.map((question) => Number(question.id));
  for (let i = ids.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [ids[i], ids[j]] = [ids[j], ids[i]];
  }
  return ids;
}

function applyPracticeStartFilter(filter = {}) {
  state.localFilter = filter.localFilter || null;
  state.practiceResultFilter = copyResultFilter(state.practiceStartResultFilter);
  setFilterSelectValue(fields.filterYear, filter.year);
  setFilterSelectValue(fields.filterCategory, filter.category);
  fields.filterKeyword.value = filter.q || "";
  state.libraryPage = 1;
}

async function startPractice(filter = {}, { forceRandom = false } = {}) {
  if (state.practiceStarting) return;
  state.questionSetPracticeActive = false;
  state.questionSetPractice = null;
  const randomStart = forceRandom || state.practiceRandomStart;
  if (
    randomStart &&
    practiceSessionInProgress() &&
    !window.confirm("進行中のランダム一周を破棄して、新しい一周を開始しますか？")
  ) {
    return;
  }

  applyPracticeStartFilter(filter);
  state.practiceOrder = null;
  state.practiceShufflePending = false;

  if (!randomStart) {
    state.practiceSessionActive = false;
    state.showStudyMap = false;
    renderFilterSummary();
    refreshAll({ keepQuestion: false }).catch((error) => toast(error.message));
    return;
  }

  const requestId = ++state.refreshRequestId;
  const flowRequestId = ++state.practiceFlowRequestId;
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  const query = selectedFilters();
  const filtersSnapshot = practiceFiltersSnapshot();
  setPracticeStarting(true);
  try {
    const questionPayload = await api(`/api/questions${query ? `?${query}` : ""}`);
    if (
      requestId !== state.refreshRequestId ||
      requestedUser !== state.currentUser ||
      requestedExam !== state.selectedExam
    ) {
      return;
    }

    const loadedQuestions = questionPayload.questions || [];
    const localQuestions = state.localFilter ? applyLocalFilter(loadedQuestions, state.localFilter) : loadedQuestions;
    const candidates = applyResultFilter(localQuestions, state.practiceResultFilter);
    if (!candidates.length) {
      state.practiceSessionActive = false;
      state.allQuestions = loadedQuestions;
      state.studyQuestions = loadedQuestions;
      state.questions = [];
      state.questionsLoaded = true;
      state.showStudyMap = false;
      renderFilterSummary();
      renderQuestionTable();
      setCurrentQuestionByIndex(0);
      return;
    }

    const questionIds = shuffledQuestionIds(candidates);
    const sessionPayload = await api("/api/practice-session", {
      method: "POST",
      body: JSON.stringify({
        user_name: requestedUser,
        exam: requestedExam,
        filters: filtersSnapshot,
        question_ids: questionIds,
      }),
    });
    if (
      requestId !== state.refreshRequestId ||
      requestedUser !== state.currentUser ||
      requestedExam !== state.selectedExam
    ) {
      return;
    }

    state.practiceSession = normalizePracticeSession(sessionPayload.practice_session);
    if (!state.practiceSession?.token) {
      throw new Error("ランダム一周を開始できませんでした。");
    }
    state.practiceSessionActive = true;
    state.practiceOrder = new Map(state.practiceSession.question_ids.map((id, rank) => [id, rank]));
    state.allQuestions = loadedQuestions;
    state.studyQuestions = loadedQuestions;
    state.questions = filteredPracticeQuestions();
    state.questionsLoaded = true;
    state.showStudyMap = false;
    renderFilterSummary();
    renderPracticeSessionCard();
    renderQuestionTable();
    setCurrentQuestionByIndex(0);
  } catch (error) {
    toast(error.message);
  } finally {
    if (flowRequestId === state.practiceFlowRequestId) setPracticeStarting(false);
  }
}

async function resumePracticeSession() {
  if (state.practiceStarting || !state.practiceSession?.token) return;
  state.questionSetPracticeActive = false;
  state.questionSetPractice = null;
  const requestId = ++state.refreshRequestId;
  const flowRequestId = ++state.practiceFlowRequestId;
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  setPracticeStarting(true);
  try {
    const params = practiceSessionParams(requestedUser, requestedExam);
    const [questionPayload, sessionPayload] = await Promise.all([
      api(`/api/questions${queryFor(params)}`),
      api(`/api/practice-session${queryFor(params)}`),
    ]);
    if (
      requestId !== state.refreshRequestId ||
      requestedUser !== state.currentUser ||
      requestedExam !== state.selectedExam
    ) {
      return;
    }

    const session = normalizePracticeSession(sessionPayload.practice_session);
    if (!session?.token) {
      state.practiceSession = null;
      state.practiceSessionActive = false;
      renderPracticeSessionCard();
      toast("保存中のランダム一周はありません。");
      return;
    }

    state.practiceSession = session;
    state.practiceSessionActive = true;
    applySavedPracticeFilters(session.filters);
    state.practiceOrder = new Map(session.question_ids.map((id, rank) => [id, rank]));
    state.practiceShufflePending = false;
    state.allQuestions = questionPayload.questions || [];
    state.studyQuestions = state.allQuestions;
    state.questions = filteredPracticeQuestions();
    state.questionsLoaded = true;
    state.libraryPage = 1;
    state.showStudyMap = false;
    renderPracticeResultFilter();
    renderFilterSummary();
    renderPracticeSessionCard();
    renderQuestionTable();
    setCurrentQuestionByIndex(0);
  } catch (error) {
    toast(error.message);
  } finally {
    if (flowRequestId === state.practiceFlowRequestId) setPracticeStarting(false);
  }
}

function restartPracticeSession() {
  const filters = state.practiceSession?.filters;
  if (!filters || state.practiceStarting) return;
  applySavedPracticeFilters(filters);
  const startFilter = {
    year: filters.year || "",
    category: filters.category || "",
    q: filters.q || "",
    localFilter: state.localFilter,
  };
  state.practiceSessionActive = false;
  void startPractice(startFilter, { forceRandom: true });
}

async function discardPracticeSession() {
  if (!state.practiceSession?.token || state.practiceStarting) return;
  if (!window.confirm("保存中のランダム一周を破棄しますか？")) return;
  const requestedUser = state.currentUser;
  const requestedExam = state.selectedExam;
  const flowRequestId = ++state.practiceFlowRequestId;
  setPracticeStarting(true);
  try {
    await api(`/api/practice-session${queryFor(practiceSessionParams(requestedUser, requestedExam))}`, {
      method: "DELETE",
    });
    if (requestedUser !== state.currentUser || requestedExam !== state.selectedExam) return;
    state.practiceSession = null;
    state.practiceSessionActive = false;
    state.practiceOrder = null;
    renderPracticeSessionCard();
    toast("保存中のランダム一周を破棄しました。");
  } catch (error) {
    toast(error.message);
  } finally {
    if (
      flowRequestId === state.practiceFlowRequestId &&
      requestedUser === state.currentUser &&
      requestedExam === state.selectedExam
    ) {
      setPracticeStarting(false);
    }
  }
}

function leavePracticeSessionForStudyMap() {
  const leavingQuestionSet = hasQuestionSetPracticeContext();
  if (state.practiceStarting) {
    state.refreshRequestId += 1;
    state.practiceFlowRequestId += 1;
    setPracticeStarting(false);
  }
  state.practiceSessionActive = false;
  state.questionSetPracticeActive = false;
  if (leavingQuestionSet) {
    state.questionSetPractice = null;
    state.studyMode = "sets";
    state.questionSetView = "list";
    state.selectedQuestionSetId = null;
    state.selectedQuestionSetRoundId = null;
  }
  state.practiceOrder = null;
  state.practiceShufflePending = false;
  state.showStudyMap = false;
  clearStudyFilters();
  showStudyMap();
  renderStudyMap();
  if (leavingQuestionSet) void refreshQuestionSets({ force: true });
  resetScroll();
}

function startStudyItem(index) {
  const item = state.studyItems[index];
  if (!item) return;
  startPractice(item.filter || {});
}

function switchExam(exam) {
  if (!exam || exam === state.selectedExam) return;
  state.selectedExam = exam;
  state.practiceSession = null;
  state.practiceSessionActive = false;
  state.practiceFlowRequestId += 1;
  clearQuestionSetState();
  clearDiseaseChecklistState();
  setPracticeStarting(false);
  state.practiceSessionRequestId += 1;
  clearStudyFilters();
  clearQuestionLists();
  state.currentQuestion = null;
  state.currentIndex = -1;
  state.resultContext = null;
  state.showStudyMap = true;
  refreshAll({ keepQuestion: false }).catch((error) => toast(error.message));
  if (state.activeTab === "diseaseChecklist") void refreshDiseaseChecklists();
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
    if (hasQuestionSetPracticeContext()) {
      const round = state.questionSetPractice.round;
      const completedIds = new Set(round.completed_question_ids);
      const roundIds = new Set(round.question_ids);
      const completedMatch = state.allQuestions.some(
        (question) =>
          roundIds.has(Number(question.id)) &&
          completedIds.has(Number(question.id)) &&
          questionNumber(question) === number,
      );
      if (completedMatch) {
        toast(`問${number}はこの周回で解答済みです。`);
        return;
      }
    }
    if (hasActivePracticeSession()) {
      const completedIds = new Set(state.practiceSession.completed_question_ids);
      const sessionIds = new Set(state.practiceSession.question_ids);
      const completedMatch = state.allQuestions.some(
        (question) =>
          sessionIds.has(Number(question.id)) &&
          completedIds.has(Number(question.id)) &&
          questionNumber(question) === number,
      );
      if (completedMatch) {
        toast(`問${number}はこの一周で解答済みです。`);
        return;
      }
    }
    toast(`問${number}は現在の条件内にありません。`);
    return;
  }

  setCurrentQuestionByIndex(index);
}

function renderPracticeRoundProgress() {
  if (!fields.practiceRoundProgress) return;
  const questionSetContext = hasQuestionSetPracticeContext();
  if (!questionSetContext && !hasActivePracticeSession()) {
    fields.practiceRoundProgress.classList.add("hidden");
    fields.practiceRoundProgress.innerHTML = "";
    return;
  }

  const session = questionSetContext ? state.questionSetPractice.round : state.practiceSession;
  const total = Math.max(0, Number(session.total || 0));
  const completed = Math.min(total, Math.max(0, Number(session.completed || 0)));
  const remaining = Math.max(0, Number(session.remaining ?? total - completed));
  const title = questionSetContext
    ? `${state.questionSetPractice.question_set?.title || "問題セット"}・第${session.round_number}周 ${completed}/${total}`
    : `一周 ${completed}/${total}`;
  fields.practiceRoundProgress.classList.remove("hidden");
  fields.practiceRoundProgress.innerHTML = `
    <strong>${escapeHtml(title)}</strong>
    <progress value="${completed}" max="${Math.max(1, total)}" aria-label="${completed}/${total}問 完了"></progress>
    <span>残り${remaining}問</span>
  `;
}

function renderPractice() {
  closeImageLightbox({ restoreFocus: false });
  const question = state.currentQuestion;
  renderPracticeRoundProgress();
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
    const quickRoundComplete =
      hasActivePracticeSession() &&
      (state.practiceSession.status === "completed" || Number(state.practiceSession.remaining || 0) === 0);
    const questionSetRound = state.questionSetPractice?.round;
    const questionSetRoundComplete =
      hasQuestionSetPracticeContext() &&
      (questionSetRound.status === "completed" || Number(questionSetRound.remaining || 0) === 0);
    const roundComplete = quickRoundComplete || questionSetRoundComplete;
    if (roundComplete && fields.practiceRoundComplete) {
      if (questionSetRoundComplete) {
        const questionSet = state.questionSetPractice.question_set;
        fields.practiceRoundComplete.innerHTML = `
          <strong>${escapeHtml(questionSet?.title || "問題セット")} 第${questionSetRound.round_number}周が完了しました</strong>
          <span>この周回で利用できる問題をすべて解答しました。結果は周回履歴に保存されています。</span>
          <div class="practice-round-complete-actions">
            <button class="primary" type="button" data-question-set-next-round="${questionSet?.id}">再シャッフルしてもう一周</button>
            <button class="ghost" type="button" data-leave-practice-session>問題セット一覧へ</button>
          </div>
        `;
      } else {
        fields.practiceRoundComplete.innerHTML = `
          <strong>ランダム一周が完了しました</strong>
          <span>開始時に選んだ問題をすべて解答しました。</span>
          <div class="practice-round-complete-actions">
            <button class="primary" type="button" data-restart-practice-session>現在の条件でもう一周</button>
            <button class="ghost" type="button" data-leave-practice-session>一覧へ戻る</button>
          </div>
        `;
      }
    }
    if (!roundComplete && fields.emptyPractice) {
      const unavailable = Number(questionSetRound?.unavailable || 0);
      fields.emptyPractice.innerHTML = hasQuestionSetPracticeContext()
        ? `
          <strong>続けられる問題がありません</strong>
          <span>${unavailable ? `${unavailable}問が利用できません。` : "この周回の状態を更新してください。"}</span>
        `
        : `<strong>問題がありません</strong><span>条件に一致する問題がありません。</span>`;
    }
    fields.practiceRoundComplete?.classList.toggle("hidden", !roundComplete);
    fields.emptyPractice.classList.toggle("hidden", roundComplete);
    fields.questionArea.classList.add("hidden");
    fields.jumpQuestionNumber.value = "";
    fields.jumpQuestionNumber.disabled = true;
    fields.prevQuestion.disabled = true;
    fields.nextQuestion.disabled = true;
    if (fields.practiceCategoryEditor) fields.practiceCategoryEditor.classList.add("hidden");
    return;
  }

  fields.practiceRoundComplete?.classList.add("hidden");
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
  const unofficialAnswer = diagnosticUnofficialAnswerLink(questionById(Number(context.question_id)));
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
  const unofficialAnswerBlock = unofficialAnswer
    ? `
      <div class="result-actions result-reference-actions">
        <a
          class="source-pdf-link"
          href="${escapeHtml(unofficialAnswer.url)}"
          target="_blank"
          rel="noopener noreferrer"
        >
          非公式解答例を見る
          <span>外部サイト・${escapeHtml(unofficialAnswer.year)}年</span>
        </a>
      </div>
    `
    : "";
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
    ${unofficialAnswerBlock}
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
  const activeQuestionSetRound = hasActiveQuestionSetRound();
  const activePracticeSession = hasActivePracticeSession();
  const requestBody = {
    question_id: context.question_id,
    user_name: state.currentUser,
    user_answer: context.user_answer,
    self_mark: context.self_mark || "warn",
  };
  if (activeQuestionSetRound) {
    requestBody.question_set_round_token = state.questionSetPractice.round.token;
  } else if (activePracticeSession) {
    requestBody.practice_session_token = state.practiceSession.token;
  }
  state.resultContext = { ...context, registering: true };
  try {
    const result = await api("/api/attempts", {
      method: "POST",
      body: JSON.stringify(requestBody),
    });
    const questionSetRoundStale = activeQuestionSetRound && result.question_set_round_stale === true;
    const sessionStale = activePracticeSession && result.practice_session_stale === true;
    if (activeQuestionSetRound && result.question_set_round) {
      state.questionSetPractice.round = normalizeQuestionSetRound(
        result.question_set_round,
        state.questionSetPractice.round,
      );
      syncQuestionSetRoundInList(state.questionSetPractice.round);
    }
    if (activePracticeSession && result.practice_session) {
      state.practiceSession = normalizePracticeSession(result.practice_session);
    }
    if (sessionStale) {
      state.practiceSessionActive = false;
    }
    recordAttemptLocally(context.question_id, {
      selfMark: result.self_mark || context.self_mark || "warn",
      graded: Boolean(result.graded),
      correct: result.correct === true,
    });
    if (questionSetRoundStale) {
      leavePracticeSessionForStudyMap();
      await refreshQuestionSets({ force: true });
      toast("解答履歴は保存されました。別の端末で周回が更新されたため、問題セット一覧から最新の状態を確認してください。");
      return;
    }
    if (sessionStale) {
      try {
        await refreshPracticeSession();
      } catch {
        // 解答履歴の保存は成功しているため、再取得失敗は次回の通常更新に委ねる。
      }
      leavePracticeSessionForStudyMap();
      toast("別の端末で一周が更新されました。最新の進捗から再開してください。");
      return;
    }
    const questionSetRoundCompleted =
      activeQuestionSetRound &&
      state.questionSetPractice?.round &&
      (state.questionSetPractice.round.status === "completed" ||
        Number(state.questionSetPractice.round.remaining || 0) === 0);
    const roundCompleted =
      activePracticeSession &&
      state.practiceSession &&
      (state.practiceSession.status === "completed" || Number(state.practiceSession.remaining || 0) === 0);
    toast(
      questionSetRoundCompleted
        ? `${state.questionSetPractice.question_set?.title || "問題セット"} 第${state.questionSetPractice.round.round_number}周が完了しました。`
        : roundCompleted
          ? "ランダム一周が完了しました。"
          : "結果を登録しました。",
    );
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
  if (
    !window.confirm(
      "通常の解答履歴、問題セットの全周回履歴（進行中を含む）、クイックランダムの進捗をすべて削除します。問題セットの定義と固定された問題構成は残ります。よろしいですか？",
    )
  ) {
    return;
  }

  try {
    const result = await api(`/api/attempts${queryFor(userScopedParams())}`, { method: "DELETE" });
    state.practiceSession = null;
    state.practiceSessionActive = false;
    clearQuestionSetState();
    toast(`${Number(result.deleted || 0)}件の通常履歴と、保存中の周回・進捗を削除しました。`);
    await refreshAll({ keepQuestion: true, renderPracticePanel: false });
    if (state.studyMode === "sets") await refreshQuestionSets({ force: true });
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
  state.practiceSessionActive = false;
  state.questionSetPracticeActive = false;
  state.questionSetPractice = null;
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
  if (name === "diseaseChecklist" && !canUseDiseaseChecklists()) {
    toast("疾患確認は指定されたTailscale管理者のみ使用できます。");
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
  if (name === "diseaseChecklist") {
    renderDiseaseChecklistView();
    if (!state.diseaseChecklistsLoaded && !state.diseaseChecklistsLoading) {
      void refreshDiseaseChecklists();
    }
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
      if (state.practiceStarting) {
        state.refreshRequestId += 1;
        state.practiceFlowRequestId += 1;
        setPracticeStarting(false);
      }
      if (tab.dataset.tab === "practice") {
        const returningFromQuestionSet = hasQuestionSetPracticeContext();
        state.practiceSessionActive = false;
        state.questionSetPracticeActive = false;
        state.questionSetPractice = null;
        if (returningFromQuestionSet) {
          state.studyMode = "sets";
          state.questionSetView = "list";
        }
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
  fields.refreshDiseaseChecklists?.addEventListener("click", () => {
    void refreshDiseaseChecklists();
  });
  fields.diseaseChecklistSelect?.addEventListener("change", () => {
    const checklistId = Number(fields.diseaseChecklistSelect.value);
    if (Number.isInteger(checklistId)) void loadDiseaseChecklist(checklistId);
  });
  fields.diseaseStatusFilter?.addEventListener("change", () => {
    state.diseaseChecklistStatusFilter = fields.diseaseStatusFilter.value;
    state.diseaseChecklistPage = 1;
    state.diseaseChecklistRecentlyReviewedItemId = null;
    renderDiseaseChecklistResults();
  });
  fields.diseaseRegionFilter?.addEventListener("change", () => {
    state.diseaseChecklistRegionFilter = fields.diseaseRegionFilter.value;
    state.diseaseChecklistPage = 1;
    state.diseaseChecklistRecentlyReviewedItemId = null;
    renderDiseaseChecklistResults();
    scrollDiseaseChecklistResultsIntoView();
  });
  fields.diseasePreviousRegion?.addEventListener("click", () => {
    moveDiseaseChecklistRegion(-1);
  });
  fields.diseaseNextRegion?.addEventListener("click", () => {
    moveDiseaseChecklistRegion(1);
  });
  fields.diseaseSearchFilter?.addEventListener("input", () => {
    state.diseaseChecklistSearchFilter = fields.diseaseSearchFilter.value;
    state.diseaseChecklistPage = 1;
    state.diseaseChecklistRecentlyReviewedItemId = null;
    renderDiseaseChecklistResults();
  });
  fields.diseaseEverWrongFilter?.addEventListener("change", () => {
    state.diseaseChecklistEverWrongFilter = fields.diseaseEverWrongFilter.checked;
    state.diseaseChecklistPage = 1;
    state.diseaseChecklistRecentlyReviewedItemId = null;
    renderDiseaseChecklistResults();
  });
  fields.diseaseAddedByWrongFilter?.addEventListener("change", () => {
    state.diseaseChecklistAddedByWrongFilter = fields.diseaseAddedByWrongFilter.checked;
    state.diseaseChecklistPage = 1;
    state.diseaseChecklistRecentlyReviewedItemId = null;
    renderDiseaseChecklistResults();
  });
  [fields.diseaseChecklistPaginationTop, fields.diseaseChecklistPaginationBottom].forEach(
    (container) => {
      container?.addEventListener("click", handleDiseaseChecklistPaginationClick);
      container?.addEventListener("change", handleDiseaseChecklistPaginationChange);
    },
  );
  fields.diseaseChecklistCards?.addEventListener("click", (event) => {
    if (event.target.closest("[data-disease-next-unreviewed]")) {
      state.diseaseChecklistRecentlyReviewedItemId = null;
      renderDiseaseChecklistCards();
      fields.diseaseChecklistCards.querySelector(".disease-card")?.scrollIntoView({ block: "start" });
      return;
    }
    const statusButton = event.target.closest("[data-disease-item-status]");
    if (statusButton) {
      void updateDiseaseChecklistItem(
        Number(statusButton.dataset.diseaseItemId),
        statusButton.dataset.diseaseItemStatus,
      );
    }
  });
  fields.exportDiseaseChecklist?.addEventListener("click", exportDiseaseChecklistTsv);
  fields.examTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-exam]");
    if (button) switchExam(button.dataset.exam);
  });
  $$(".study-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.studyMode = tab.dataset.studyMode;
      if (state.studyMode === "sets") state.questionSetView = "list";
      renderStudyMap();
    });
  });
  fields.studyList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-study-index]");
    if (button) startStudyItem(Number(button.dataset.studyIndex));
  });
  fields.startAllRandom?.addEventListener("click", () => {
    void startPractice({}, { forceRandom: true });
  });
  fields.practiceSessionCard?.addEventListener("click", (event) => {
    if (event.target.closest("[data-resume-practice-session]")) {
      void resumePracticeSession();
      return;
    }
    if (event.target.closest("[data-restart-practice-session]")) {
      restartPracticeSession();
      return;
    }
    if (event.target.closest("[data-discard-practice-session]")) {
      void discardPracticeSession();
    }
  });
  fields.refreshQuestionSets?.addEventListener("click", () => {
    void refreshQuestionSets({ force: true });
  });
  fields.questionSetPanel?.addEventListener("click", (event) => {
    const backList = event.target.closest("[data-question-set-back-list]");
    if (backList) {
      showQuestionSetList();
      return;
    }
    const backHistory = event.target.closest("[data-question-set-back-history]");
    if (backHistory) {
      showQuestionSetHistoryFromDetail();
      return;
    }
    const startButton = event.target.closest("[data-question-set-start]");
    if (startButton) {
      startQuestionSetRound(Number(startButton.dataset.questionSetStart));
      return;
    }
    const resumeButton = event.target.closest("[data-question-set-resume]");
    if (resumeButton) {
      void openQuestionSetRoundForPractice(Number(resumeButton.dataset.questionSetResume));
      return;
    }
    const restartButton = event.target.closest("[data-question-set-restart]");
    if (restartButton) {
      restartQuestionSetRound(Number(restartButton.dataset.questionSetRestart));
      return;
    }
    const abandonButton = event.target.closest("[data-question-set-abandon]");
    if (abandonButton) {
      void abandonQuestionSetRound(
        Number(abandonButton.dataset.questionSetAbandon),
        Number(abandonButton.dataset.roundId),
      );
      return;
    }
    const historyButton = event.target.closest("[data-question-set-history]");
    if (historyButton) {
      void openQuestionSetHistory(Number(historyButton.dataset.questionSetHistory), 0);
      return;
    }
    const detailButton = event.target.closest("[data-question-set-round-detail]");
    if (detailButton) {
      void openQuestionSetRoundDetail(
        state.selectedQuestionSetId,
        Number(detailButton.dataset.questionSetRoundDetail),
        0,
      );
      return;
    }
    const deleteRoundButton = event.target.closest("[data-question-set-round-delete]");
    if (deleteRoundButton) {
      void deleteQuestionSetRound(Number(deleteRoundButton.dataset.questionSetRoundDelete));
      return;
    }
    const deleteSetButton = event.target.closest("[data-question-set-delete]");
    if (deleteSetButton) {
      void deleteQuestionSet(Number(deleteSetButton.dataset.questionSetDelete));
    }
  });
  fields.questionSetRoundPrev?.addEventListener("click", () => {
    void openQuestionSetHistory(
      state.selectedQuestionSetId,
      Math.max(0, state.questionSetRoundsOffset - QUESTION_SET_ROUND_PAGE_SIZE),
    );
  });
  fields.questionSetRoundNext?.addEventListener("click", () => {
    void openQuestionSetHistory(
      state.selectedQuestionSetId,
      state.questionSetRoundsOffset + QUESTION_SET_ROUND_PAGE_SIZE,
    );
  });
  fields.questionSetRoundItemPrev?.addEventListener("click", () => {
    void openQuestionSetRoundDetail(
      state.selectedQuestionSetId,
      state.selectedQuestionSetRoundId,
      Math.max(0, state.questionSetRoundItemsOffset - QUESTION_SET_ROUND_ITEM_PAGE_SIZE),
    );
  });
  fields.questionSetRoundItemNext?.addEventListener("click", () => {
    void openQuestionSetRoundDetail(
      state.selectedQuestionSetId,
      state.selectedQuestionSetRoundId,
      state.questionSetRoundItemsOffset + QUESTION_SET_ROUND_ITEM_PAGE_SIZE,
    );
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
    leavePracticeSessionForStudyMap();
  });
  $("#applyFilters").addEventListener("click", () => {
    if (state.practiceStarting) {
      state.refreshRequestId += 1;
      state.practiceFlowRequestId += 1;
      setPracticeStarting(false);
    }
    state.practiceSessionActive = false;
    state.questionSetPracticeActive = false;
    state.questionSetPractice = null;
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
  fields.practiceSession.addEventListener("click", (event) => {
    const nextQuestionSetRound = event.target.closest("[data-question-set-next-round]");
    if (nextQuestionSetRound) {
      startQuestionSetRound(Number(nextQuestionSetRound.dataset.questionSetNextRound));
      return;
    }
    if (event.target.closest("[data-restart-practice-session]")) {
      restartPracticeSession();
      return;
    }
    if (event.target.closest("[data-leave-practice-session]")) {
      leavePracticeSessionForStudyMap();
    }
  });
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
