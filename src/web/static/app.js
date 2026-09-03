/* =========================================================================
 * app.js — שכבת השאלות והתשובות של בונה המערכת, בדפדפן.
 * The whole client. Vanilla ES2020. No framework, no build step, no CDN.
 *
 * ארכיטקטורה (architecture) בשלוש שורות:
 *   1. אובייקט מצב אחד (``state``). כל שינוי עובר דרך setState().
 *   2. setState() שומר ל-localStorage, מרנדר מחדש, ומזמן solve בהשהיה קצרה.
 *   3. כל בקשה מסומנת במספר רץ; תשובה ישנה שמגיעה באיחור — מושלכת.
 *
 * אבטחה (security): אין בקובץ הזה אף שימוש ב-innerHTML. כל טקסט שמגיע
 * מהידיעון (שמות קורסים, מרצים, הערות) נכנס ל-DOM דרך textContent או
 * setAttribute בלבד, ולכן לא יכול להתפרש כ-HTML.
 *
 * הקובץ הזה מפעיל את ה-DOM ש-``templates/index.html`` מגדיר, לפי חוזה
 * המזהים שכתוב שם. הוא לא בונה מבנה משלו ולא מזריק CSS: אם אלמנט חסר,
 * החלק שתלוי בו פשוט לא מצויר — ושאר העמוד ממשיך לעבוד.
 * ========================================================================= */

(function () {
  "use strict";

  /* =====================================================================
   * 1. קבועים
   * ===================================================================== */

  var STORAGE_KEY = "braude_schedule_builder_v1";
  var STORAGE_SCHEMA = 1;

  var SOLVE_DEBOUNCE_MS = 150;
  var SEARCH_DEBOUNCE_MS = 250;
  /** כמה שורות קטלוג להביא בכל עיון. מספיק כדי לגלול, מעט מספיק כדי לטעון מיד. */
  var BROWSE_LIMIT = 60;
  var SCRAPE_POLL_MS = 2000;
  var TOAST_MS = 5000;

  /** רזולוציית הרשת השבועית: שורה לכל רבע שעה (כמו בחוזה שב-index.html). */
  var SLOT_MINUTES = 15;
  var GRID_DEFAULT_START = 8 * 60; // 08:00
  var GRID_DEFAULT_END = 20 * 60; // 20:00

  var DAY_LETTERS = { 1: "א", 2: "ב", 3: "ג", 4: "ד", 5: "ה", 6: "ו" };
  var DAY_NAMES = {
    1: "ראשון",
    2: "שני",
    3: "שלישי",
    4: "רביעי",
    5: "חמישי",
    6: "שישי",
  };
  var DAYS = [1, 2, 3, 4, 5, 6];

  /** סדר תצוגה של סוגי רכיב — זהה ל-models.KIND_ORDER. */
  var KIND_ORDER = ["הרצאה", "תרגול", "מעבדה", "פרויקט", 'שו"ת', "אחר"];

  var TERMS_FALLBACK = [
    { value: "א", label: "סמסטר א׳ (חורף)" },
    { value: "ב", label: "סמסטר ב׳ (אביב)" },
    { value: "קיץ", label: "סמסטר קיץ" },
  ];

  var YEAR_LABELS = { 1: "שנה א׳", 2: "שנה ב׳", 3: "שנה ג׳", 4: "שנה ד׳" };

  /**
   * קורסים צמודים — רשת ביטחון בלבד.
   * המקור האמיתי הוא ``tied_with`` שמגיע מהשרת (מתוך curriculum.json);
   * זה נכנס לפעולה רק אם השדה חסר.
   */
  var TIED_FALLBACK = [["61756", "61757", "62027"]];

  /**
   * סימן בהערת הידיעון שקובע את ברירת המחדל של חובת נוכחות.
   * ‏SPEC_V2 §2: הערה כזו רק *מסמנת מקור* — ברירת המחדל היא חובה בכל מקרה,
   * והוויתור עליה הוא תמיד בחירה מפורשת של הסטודנט/ית.
   */
  var ATTENDANCE_NOTE_RE = /חובת\s*ה?נוכחות|חובה\s*להשתתף|נוכחות\s*חובה/;

  var PALETTE_SIZE = 10; // ‏c0..c9, בדיוק כמו הפלטה ב-render.py

  var BREAKDOWN_HE = {
    lecturer: "מרצים",
    days: "ימים",
    gaps: "חורים",
    compactness: "צפיפות",
  };

  var PHASE_HE = {
    warmup: "פותח סשן מול הידיעון",
    session: "פותח סשן מול הידיעון",
    year: "קובע שנת לימודים",
    verify: "מאמת את השנה שחזרה",
    store: "שומר למסד",
    finishing: "מסיים",
    idle: "ממתין",
    starting: "מתחיל",
    login: "ממתין להתחברות ידנית",
    connected: "מחובר לידיעון",
    search: "מחפש קורסים",
    fetch: "מושך עמודים",
    fetching: "מושך עמודים",
    parse: "מפענח",
    parsing: "מפענח",
    save: "שומר למסד",
    saving: "שומר למסד",
    catalog: "מושך קטלוג",
    done: "הסתיים",
    failed: "נכשל",
    needs_login: "נדרשת התחברות",
  };

  /* =====================================================================
   * 2. עזרי יסוד
   * ===================================================================== */

  /** כל טקסט שנכנס ל-DOM עובר כאן: null/undefined הופכים למחרוזת ריקה. */
  function txt(value) {
    if (value === null || value === undefined) return "";
    return String(value);
  }

  function num(value, fallback) {
    var n = typeof value === "number" ? value : parseFloat(value);
    return isFinite(n) ? n : fallback;
  }

  function clamp(n, lo, hi) {
    return Math.min(hi, Math.max(lo, n));
  }

  /** "08:30" / 510 -> 510 דקות מחצות. */
  function toMinutes(value) {
    if (typeof value === "number" && isFinite(value)) return Math.round(value);
    var s = txt(value).trim();
    var m = /^(\d{1,2}):(\d{2})$/.exec(s);
    if (m) return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
    var n = parseFloat(s);
    return isFinite(n) ? Math.round(n) : 0;
  }

  /** 510 -> "08:30". */
  function fmtTime(minutes) {
    var m = toMinutes(minutes);
    var h = Math.floor(m / 60);
    var mm = m % 60;
    return (h < 10 ? "0" : "") + h + ":" + (mm < 10 ? "0" : "") + mm;
  }

  /** 410 -> "6:50". */
  function fmtSpan(minutes) {
    var m = Math.max(0, Math.round(num(minutes, 0)));
    var h = Math.floor(m / 60);
    var mm = m % 60;
    return h + ":" + (mm < 10 ? "0" : "") + mm;
  }

  /** מספר "יפה": 19 ולא 19.0, אבל 2.5 נשאר 2.5. */
  function fmtNumber(value) {
    var n = num(value, 0);
    var rounded = Math.round(n * 10) / 10;
    return String(rounded);
  }

  function dayLetter(day) {
    return DAY_LETTERS[day] || "?";
  }

  function dayName(day) {
    return DAY_NAMES[day] || "";
  }

  /**
   * CRC32 — אותו אלגוריתם ש-``render.py`` משתמש בו למיפוי צבעים,
   * כדי שאותו קורס יקבל את אותו גוון גם בדפדפן וגם בקובץ ה-HTML שנוצר במסוף.
   */
  var CRC_TABLE = (function () {
    var table = new Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) {
        c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      }
      table[n] = c >>> 0;
    }
    return table;
  })();

  function crc32(str) {
    var c = 0xffffffff;
    var s = txt(str);
    for (var i = 0; i < s.length; i++) {
      var code = s.charCodeAt(i);
      // הקודים הם ספרות ASCII; בכל זאת מקודדים UTF-8 כדי להתאים ל-Python.
      var bytes =
        code < 0x80
          ? [code]
          : code < 0x800
          ? [0xc0 | (code >> 6), 0x80 | (code & 0x3f)]
          : [0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f)];
      for (var b = 0; b < bytes.length; b++) {
        c = CRC_TABLE[(c ^ bytes[b]) & 0xff] ^ (c >>> 8);
      }
    }
    return (c ^ 0xffffffff) >>> 0;
  }

  /**
   * ‏{קוד קורס: אינדקס צבע} — העתק מדויק של ``render.build_color_map``:
   * ‏crc32 לבחירה ראשונית, ואז "דילוג" לגוון הפנוי הבא לפי סדר קודים ממוין.
   */
  function buildColorMap(codes) {
    var sorted = uniq(codes.map(txt)).sort();
    var used = Object.create(null);
    var usedCount = 0;
    var map = Object.create(null);
    sorted.forEach(function (code) {
      var idx = crc32(code.trim()) % PALETTE_SIZE;
      if (usedCount < PALETTE_SIZE) {
        for (var step = 0; step < PALETTE_SIZE; step++) {
          var candidate = (idx + step) % PALETTE_SIZE;
          if (!used[candidate]) {
            idx = candidate;
            break;
          }
        }
      }
      map[code] = idx;
      if (!used[idx]) {
        used[idx] = true;
        usedCount++;
      }
    });
    return map;
  }

  /** גיל בעברית, ניטרלי מגדרית. נכנס לפעולה רק כשהשרת לא שלח טקסט משלו. */
  function agoHebrew(isoOrEpoch) {
    var t = null;
    if (typeof isoOrEpoch === "number" && isFinite(isoOrEpoch)) {
      t = isoOrEpoch > 1e12 ? isoOrEpoch : isoOrEpoch * 1000;
    } else if (isoOrEpoch) {
      var parsed = Date.parse(txt(isoOrEpoch));
      if (!isNaN(parsed)) t = parsed;
    }
    if (t === null) return "";
    var secs = Math.max(0, (Date.now() - t) / 1000);
    if (secs < 60) return "לפני פחות מדקה";
    var mins = Math.floor(secs / 60);
    if (mins < 60) return mins === 1 ? "לפני דקה" : "לפני " + mins + " דקות";
    var hours = Math.floor(mins / 60);
    if (hours < 24) return hours === 1 ? "לפני שעה" : "לפני " + hours + " שעות";
    var days = Math.floor(hours / 24);
    if (days === 1) return "לפני יום";
    if (days < 30) return "לפני " + days + " ימים";
    var months = Math.floor(days / 30);
    return months === 1 ? "לפני חודש" : "לפני " + months + " חודשים";
  }

  /** בניית אלמנט. כל טקסט עובר דרך textContent — לעולם לא innerHTML. */
  function el(tag, opts, kids) {
    var node = document.createElement(tag);
    opts = opts || {};
    if (opts.class) node.className = opts.class;
    if (opts.text !== undefined && opts.text !== null) {
      node.textContent = txt(opts.text);
    }
    if (opts.attrs) {
      Object.keys(opts.attrs).forEach(function (k) {
        var v = opts.attrs[k];
        if (v !== null && v !== undefined && v !== false && v !== "") {
          node.setAttribute(k, txt(v));
        }
      });
    }
    if (opts.data) {
      Object.keys(opts.data).forEach(function (k) {
        var v = opts.data[k];
        if (v !== null && v !== undefined) node.dataset[k] = txt(v);
      });
    }
    if (opts.style) {
      Object.keys(opts.style).forEach(function (k) {
        node.style.setProperty(k, opts.style[k]);
      });
    }
    if (opts.on) {
      Object.keys(opts.on).forEach(function (k) {
        node.addEventListener(k, opts.on[k]);
      });
    }
    (kids || []).forEach(function (kid) {
      if (kid) node.appendChild(kid);
    });
    return node;
  }

  function clear(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
  }

  function setText(node, value) {
    if (node) node.textContent = txt(value);
  }

  function setHidden(node, hidden) {
    if (node) node.hidden = !!hidden; // ‏[hidden] מטופל ב-CSS, בלי style.display
  }

  function setClass(node, name, on) {
    if (!node) return;
    var parts = txt(node.className).split(/\s+/).filter(Boolean);
    var i = parts.indexOf(name);
    if (on && i === -1) parts.push(name);
    if (!on && i !== -1) parts.splice(i, 1);
    node.className = parts.join(" ");
  }

  /**
   * בנייה מחדש של מכולה תוך שמירת הפוקוס.
   * לכל פקד אינטראקטיבי יש data-fk ייחודי; אחרי הבנייה מחזירים אליו פוקוס.
   */
  function rebuild(container, build) {
    if (!container) return;
    var key = null;
    var active = document.activeElement;
    if (active && container.contains && container.contains(active)) {
      key = active.dataset ? active.dataset.fk || null : null;
    }
    clear(container);
    build(container);
    if (!key) return;
    var candidates = container.querySelectorAll("[data-fk]");
    for (var i = 0; i < candidates.length; i++) {
      if (candidates[i].dataset.fk === key) {
        try {
          candidates[i].focus();
        } catch (e) {
          /* פוקוס נכשל — לא סיבה להפיל רינדור */
        }
        return;
      }
    }
  }

  /** רשימה מנורמלת: מערך, או אובייקט {code: rec}, או null. */
  function asList(value, keyField) {
    if (Array.isArray(value)) return value.slice();
    if (value && typeof value === "object") {
      return Object.keys(value).map(function (k) {
        var rec = value[k];
        if (rec && typeof rec === "object") {
          var copy = Object.assign({}, rec);
          if (keyField && copy[keyField] === undefined) copy[keyField] = k;
          return copy;
        }
        var made = {};
        if (keyField) made[keyField] = k;
        made.value = rec;
        return made;
      });
    }
    return [];
  }

  /** שולף רשימה מהתשובה, לא משנה באיזה שדה השרת שם אותה. */
  function pickList(data, names, keyField) {
    if (!data) return [];
    for (var i = 0; i < names.length; i++) {
      var v = data[names[i]];
      if (v !== undefined && v !== null) return asList(v, keyField);
    }
    return Array.isArray(data) ? data.slice() : [];
  }

  function deepCopy(value) {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (e) {
      return value;
    }
  }

  function uniq(list) {
    var seen = Object.create(null);
    var out = [];
    list.forEach(function (item) {
      var k = txt(item);
      if (!seen[k]) {
        seen[k] = true;
        out.push(item);
      }
    });
    return out;
  }

  function byId(id) {
    return document.getElementById(id);
  }

  /* =====================================================================
   * 3. מצב + שמירה מקומית
   * ===================================================================== */

  function defaultState() {
    return {
      schema: STORAGE_SCHEMA,
      studyYear: 3, // שנה בתוכנית (1..4)
      term: "א", // סמסטר בידיעון: א / ב / קיץ
      semester: "5", // סמסטר בתוכנית הלימודים (1..8), "" אם אין
      academicYear: "", // שנה"ל (למשל תשפ"ז) — מגיע מהשרת
      codes: [], // קודי הקורסים שנבחרו, לפי סדר הוספה
      // מקור הבחירה. ‏codes נשאר מקור האמת היחיד לציור; שלושת אלה רק זוכרים
      // *מי* סימן כל קורס, כדי שהחלפת שנה/סמסטר תחליף את ההמלצה בלי לגעת
      // במה שנבחר ידנית, וכדי שביטול ידני של קורס מומלץ לא יבוטל על ידי
      // משיכה מאוחרת של אותה רשימה.
      autoSemester: "", // הסמסטר שההמלצה שלו מוחלת כרגע. "" = אין המלצה מוחלת
      autoCodes: [], // מה שסומן אוטומטית עבור autoSemester
      manualCodes: [], // מה שנוסף ידנית (חיפוש/קטלוג/בחירה) — שורד החלפת סמסטר
      autoDropped: [], // קורסים מומלצים שבוטלו ידנית — לא לסמן שוב
      // האם כבר קבענו מקור לכל קוד שנבחר. ‏autoSemester ריק אינו סימן טוב
      // מספיק לשאלה הזאת: הוא ריק גם לפני ההחלה הראשונה וגם אחרי מעבר
      // לקיץ, ובלי הבחנה ביניהם חזרה מקיץ הייתה מסמנת את כל ההמלצה
      // כ"בוטלה" ומשאירה את הרשימה ריקה.
      provenanceReady: false,
      known: {}, // מטמון שמות/נ"ז: {code: {name, credits, semester}}
      targetDays: 4,
      forbidFriday: false,
      // {code: {kind: האם יש חובת נוכחות}} — מפתח חסר פירושו חובה, בדיוק כמו בשרת.
      attendance: {},
      // מתג כללי: לאפשר חפיפה כשלפחות צד אחד בלי חובת נוכחות. כבוי כברירת מחדל.
      // תמיד true: סימון חובת הנוכחות הוא הפקד היחיד. אין עוד מתג נפרד
      // שאפשר לשכוח להדליק, וזו בדיוק התקלה שדווחה.
      allowSoftConflicts: true,
      // המסלול שנבחר בשלב 1. ‏rec.pdf הוא פרק הנדסת תוכנה בלבד, ולכן רשימת
      // הקורסים של שלב 2 רלוונטית רק למי שלומד/ת אותו. לכל השאר — הקטלוג.
      program: "",
      earliest: null, // דקות מחצות, או null
      latest: null,
      blocked: [], // [[יום, התחלה, סוף], ...]
      pinned: {}, // {code: {kind: group_id}}
      ranked: {}, // {code: [שם מרצה, ...]}
      topN: 5,
      activeSchedule: 0,
    };
  }

  var state = defaultState();

  /** מה שלא נשמר בין רענונים: תשובות שרת, סטטוס, שגיאות. */
  var runtime = {
    restored: false,
    ready: false,
    bootstrap: null,
    bootstrapError: null,
    semesterCourses: [],
    semesterError: null,
    catalogQuery: "",
    catalogResults: [],
    catalogError: null,
    catalogBusy: false,
    // ‏SPEC §4 — מצב קטלוג. תוכנית הלימודים היא העשרה, לא תנאי: כשאין ממנה
    // קורסים, שלב 2 עובר לעיון בקטלוג המלא במקום להישאר מסך ריק בלי הסבר.
    curriculumAvailable: null, // מ-/api/bootstrap. null = השרת לא אמר
    programs: [], // רשימת המסלולים מ-/api/bootstrap
    // קבוצות קורסי הבחירה של המסלול, מ-/api/program/electives.
    // null = עוד לא נשאל; available:false = אין מה להציג, ומסתירים.
    electives: null,
    electivesFor: "",
    electivesBusy: false,
    semesterCurriculumAvailable: null, // מ-/api/semester/<n>/courses
    // כמה קורסים יש בקטלוג שנמשך. ‏null = השרת עוד לא ענה, 0 = הקטלוג באמת
    // ריק (התקנה טרייה). בשני המקרים אסור להסיק מ-``offered: false`` שקורס
    // אינו נפתח — אין נתונים, וזה לא אותו דבר.
    semesterCatalogCount: null,
    // הסמסטר שהבחירה השמורה שייכת לו, כפי שנקרא ב-boot. ריק = אין מצב שמור.
    adoptSemester: "",
    // ‏limits.max_codes מהשרת. חורגים ממנו ⇒ כל /api/courses ו-/api/solve
    // מחזירים 400 והאפליקציה נראית שבורה לגמרי, ולכן ההמלצה נחתכת מראש.
    maxCodes: 0,
    semesterBusy: false,
    semesterFetched: false, // האם כבר יש תשובה על רשימת הסמסטר
    browseQuery: "",
    browseResults: [],
    browseTotal: null,
    browseError: null,
    browseBusy: false,
    browseLoaded: false,
    courses: [],
    notOffered: [],
    coursesError: null,
    coursesBusy: false,
    solve: null,
    solveError: null,
    solveBusy: false,
    scrape: {
      running: false,
      phase: "idle",
      log: [],
      exit_code: null,
      needs_login: false,
      message: "",
      error: "",
      // סיכום השורה האחת שמוצג בכותרת; היומן המלא נשאר מקופל.
      codes: [],
      total: null,
      done: null,
      updated: null,
      changed: null,
      summary: "",
    },
    scrapeError: null,
    logShown: 0,
    polling: false,
    reparseBusy: false,
    colors: Object.create(null),
    dismissed: Object.create(null),
    // ‏SPEC_V2 §1 — משיכה לפי דרישה: קודים שנמשכים ממש עכשיו, והמקור שחזר לכל קוד.
    fetching: Object.create(null),
    sources: Object.create(null),
    fetchSkipped: [],
    // ‏attendance_info מהשרת: {קוד: {סוג: {required, from_yedion, note, source, text}}}
    attendanceInfo: Object.create(null),
  };

  function saveState() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) {
      /* חלון פרטי / אחסון חסום — האפליקציה חייבת להמשיך לעבוד */
    }
  }

  function loadState() {
    var raw = null;
    try {
      raw = window.localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return false;
    }
    if (!raw) return false;
    var parsed = null;
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      return false;
    }
    if (!parsed || typeof parsed !== "object") return false;
    if (num(parsed.schema, 0) !== STORAGE_SCHEMA) return false;

    var base = defaultState();
    Object.keys(base).forEach(function (k) {
      if (parsed[k] !== undefined && parsed[k] !== null) base[k] = parsed[k];
    });
    if (!Array.isArray(base.codes)) base.codes = [];
    base.codes = uniq(base.codes.map(txt).filter(Boolean));
    // ‏STORAGE_SCHEMA לא עולה בגלל השדות האלה: ההשוואה ב-loadState היא שוויון
    // מוחלט בלי מסלול הגירה, והעלאה הייתה מוחקת לכל משתמש קיים את הנעיצות,
    // דירוג המרצים, החלונות החסומים וחובות הנוכחות. הוספת שדות אינה דורשת זאת.
    base.autoSemester = txt(base.autoSemester);
    ["autoCodes", "manualCodes", "autoDropped"].forEach(function (k) {
      if (!Array.isArray(base[k])) base[k] = [];
      base[k] = uniq(base[k].map(txt).filter(Boolean));
    });
    // מצב שנשמר לפני שהשדות האלה היו קיימים מגיע בלי הדגל, ולכן בלי מקור
    // ידוע לקודים שבו — בדיוק המקרה שהאימוץ ב-applyRecommendedDefaults נועד לו.
    base.provenanceReady = base.provenanceReady === true;
    if (!base.known || typeof base.known !== "object") base.known = {};
    if (!base.pinned || typeof base.pinned !== "object") base.pinned = {};
    if (!base.ranked || typeof base.ranked !== "object") base.ranked = {};
    if (!base.attendance || typeof base.attendance !== "object") base.attendance = {};
    base.allowSoftConflicts = true;  // גם מצב ישן שנשמר ב-localStorage מיושר
    if (!Array.isArray(base.blocked)) base.blocked = [];
    base.targetDays = clamp(Math.round(num(base.targetDays, 4)), 2, 6);
    base.topN = clamp(Math.round(num(base.topN, 5)), 1, 20);
    base.studyYear = clamp(Math.round(num(base.studyYear, 3)), 1, 4);
    base.activeSchedule = Math.max(0, Math.round(num(base.activeSchedule, 0)));
    if (base.earliest !== null) base.earliest = num(base.earliest, null);
    if (base.latest !== null) base.latest = num(base.latest, null);
    state = base;
    return true;
  }

  function clearSavedState() {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      /* אין אחסון — אין מה למחוק */
    }
  }

  var solveTimer = null;

  /**
   * שער יחיד לכל שינוי מצב.
   * ‏patch הוא אובייקט או פונקציה שמקבלת את המצב ומשנה אותו.
   */
  function setState(patch, opts) {
    opts = opts || {};
    if (typeof patch === "function") {
      patch(state);
    } else if (patch) {
      Object.keys(patch).forEach(function (k) {
        state[k] = patch[k];
      });
    }
    saveState();
    render();
    if (opts.solve !== false) syncData();
  }

  /* =====================================================================
   * 4. שכבת ה-HTTP
   * ===================================================================== */

  function request(path, options) {
    var opts = Object.assign({}, options || {});
    opts.headers = Object.assign(
      { Accept: "application/json" },
      (options && options.headers) || {}
    );
    if (opts.body) opts.headers["Content-Type"] = "application/json";
    return fetch(path, opts).then(function (res) {
      return res.text().then(function (raw) {
        var data = null;
        if (raw) {
          try {
            data = JSON.parse(raw);
          } catch (e) {
            data = null;
          }
        }
        if (!res.ok || !data || data.ok === false) {
          var msg =
            (data && (data.error || data.message)) ||
            "השרת החזיר תשובה לא צפויה (" + res.status + ")";
          var err = new Error(txt(msg));
          err.status = res.status;
          err.detail = data ? data.detail : raw ? raw.slice(0, 400) : "";
          err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  function getJSON(path) {
    return request(path, { method: "GET" });
  }

  function postJSON(path, body) {
    return request(path, { method: "POST", body: JSON.stringify(body || {}) });
  }

  function errorText(err) {
    if (!err) return "שגיאה לא ידועה";
    return txt(err.message) || "שגיאה לא ידועה";
  }

  /** מספרים רצים — תשובה שמגיעה אחרי בקשה חדשה יותר נזרקת. */
  var seq = { semester: 0, courses: 0, solve: 0, catalog: 0, browse: 0, electives: 0 };

  /* =====================================================================
   * 5. נגזרות מהמצב
   * ===================================================================== */

  function bootSemesters() {
    return runtime.bootstrap
      ? pickList(runtime.bootstrap, ["semesters"], "semester")
      : [];
  }

  function semesterOf(studyYear, term) {
    var list = bootSemesters();
    for (var i = 0; i < list.length; i++) {
      var rec = list[i];
      var y = num(rec.year !== undefined ? rec.year : rec.study_year, null);
      var t = txt(rec.term || rec.term_letter || "");
      if (y === studyYear && t === term) {
        return txt(rec.semester !== undefined ? rec.semester : rec.number);
      }
    }
    // הרשימה שהשרת שלח היא הקובעת. צירוף שאין לו שורה בה פשוט
    // אינו סמסטר בתוכנית — תוכנית בת 6 סמסטרים, קיץ, או מחלקה שהתוכנית
    // שלה איננה טעונה כלל. ניחוש אריתמטי שם היה שולח בקשה לסמסטר
    // שאינו קיים, מקבל 404, ומציג באנר אדום על בחירה לגיטימית.
    // ‏SPEC_MULTIFACULTY §5.
    if (list.length) return "";
    if (runtime.curriculumAvailable === false) return "";
    // רק כשהשרת לא אמר כלום (שרת ישן): 8 סמסטרים, שניים בשנה.
    if (term === "א") return String(studyYear * 2 - 1);
    if (term === "ב") return String(studyYear * 2);
    return "";
  }

  /**
   * האם מותר לדבר על "סמסטר בתוכנית הלימודים". בלי תוכנית טעונה
   * המשפט הזה מצהיר על השתייכות שאינה קיימת — SPEC_MULTIFACULTY §5 אוסר.
   */
  function curriculumSemesterKnown() {
    return runtime.curriculumAvailable !== false && !!txt(state.semester);
  }

  function semesterInfo(sem) {
    var list = bootSemesters();
    for (var i = 0; i < list.length; i++) {
      if (txt(list[i].semester) === txt(sem)) return list[i];
    }
    return null;
  }

  function yearOptions() {
    var list = runtime.bootstrap ? pickList(runtime.bootstrap, ["years"], null) : [];
    var out = [];
    list.forEach(function (rec) {
      var y = num(rec.year, null);
      if (y === null) return;
      out.push({ value: y, label: txt(rec.label) || YEAR_LABELS[y] || "שנה " + y });
    });
    if (out.length) return out;

    var years = [];
    bootSemesters().forEach(function (rec) {
      var y = num(rec.year, null);
      if (y !== null && years.indexOf(y) === -1) years.push(y);
    });
    if (!years.length) years = [1, 2, 3, 4];
    years.sort(function (a, b) {
      return a - b;
    });
    return years.map(function (y) {
      return { value: y, label: YEAR_LABELS[y] || "שנה " + y };
    });
  }

  function termOptions() {
    var list = runtime.bootstrap ? pickList(runtime.bootstrap, ["terms"], "term") : [];
    var out = [];
    list.forEach(function (rec) {
      var v = txt(rec.term);
      if (!v) return;
      out.push({ value: v, label: txt(rec.label) || "סמסטר " + v });
    });
    return out.length ? out : TERMS_FALLBACK;
  }

  /* --- מצב הקטלוג: יש רשימת קורסים מהתוכנית, או בוחרים ישירות? ------- */

  /**
   * ‏``curriculum_available`` מהשרת. השדה חדש, ושרת שאינו מכיר אותו פשוט
   * לא שולח אותו — ואז התשובה היא ``null`` ("לא ידוע") והממשק מסיק מהרשימה.
   */
  function readCurriculumAvailable(data) {
    if (!data || typeof data !== "object") return null;
    if (typeof data.curriculum_available === "boolean") return data.curriculum_available;
    var holders = [data.curriculum, data.features, data.info];
    for (var i = 0; i < holders.length; i++) {
      var h = holders[i];
      if (!h || typeof h !== "object") continue;
      if (typeof h.available === "boolean") return h.available;
      if (typeof h.curriculum_available === "boolean") return h.curriculum_available;
    }
    return null;
  }

  /**
   * למה שלב 2 עובר לקטלוג. מחרוזת ריקה = לא עובר.
   * ‏SPEC §4: אסור שסטודנט/ית מחוץ למחלקה יישאר/תישאר מול רשימה ריקה בלי הסבר.
   */
  function catalogFallbackReason() {
    if (!runtime.ready) return "";
    // בלי שתי השורות האלה מסך הפתיחה היה מהבהב במצב קטלוג לרגע, לפני
    // שרשימת הסמסטר הספיקה לחזור — ואז נעלם. הבהוב כזה נראה כמו תקלה.
    if (!runtime.semesterFetched) return "";
    if (runtime.semesterBusy) return "";
    if (runtime.semesterCourses.length) return "";
    if (runtime.curriculumAvailable === false) return "no-curriculum";
    if (runtime.semesterCurriculumAvailable === false) return "no-curriculum";
    if (runtime.semesterError) return "no-list";
    return "empty-semester";
  }

  function catalogFallbackActive() {
    return catalogFallbackReason() !== "";
  }

  /**
   * ‏/api/catalog/browse לא ענה (שרת ישן, או תקלה).
   * במצב הזה חוזרים לרשימה הנפתחת של /api/catalog/search — אחרת מצב הקטלוג
   * היה *מונע* הוספת קורסים במקום לאפשר אותה.
   */
  function catalogBrowseBroken() {
    return !!runtime.browseError && !runtime.browseResults.length;
  }

  /** האם תיבת החיפוש מזינה כרגע את רשימת הקטלוג (ולא את הרשימה הנפתחת). */
  function browseDrivesSearchBox() {
    return catalogFallbackActive() && !catalogBrowseBroken();
  }

  /** שורה אחת קצרה לכל סיבה. לא באנר, לא פסקה — שורה. */
  var FALLBACK_NOTE = {
    "no-curriculum": "תוכנית הלימודים של המחלקה לא טעונה — אפשר לבחור כל קורס מהקטלוג.",
    "no-list": "רשימת הקורסים של הסמסטר לא נטענה — אפשר לבחור כל קורס מהקטלוג.",
    "empty-semester": "אין רשימת קורסים לסמסטר הזה — אפשר לבחור כל קורס מהקטלוג.",
  };

  var BROWSE_PLACEHOLDER = 'שם, קוד או תחילית קוד — למשל 110 או חדו"א';

  function semesterCourseByCode(code) {
    for (var i = 0; i < runtime.semesterCourses.length; i++) {
      if (txt(runtime.semesterCourses[i].code) === txt(code)) {
        return runtime.semesterCourses[i];
      }
    }
    return null;
  }

  function courseDataByCode(code) {
    for (var i = 0; i < runtime.courses.length; i++) {
      if (txt(runtime.courses[i].code) === txt(code)) return runtime.courses[i];
    }
    return null;
  }

  function nameOf(code) {
    var c = courseDataByCode(code);
    if (c && txt(c.name)) return txt(c.name);
    var s = semesterCourseByCode(code);
    if (s && txt(s.name)) return txt(s.name);
    var k = state.known[txt(code)];
    if (k && txt(k.name)) return txt(k.name);
    return "קורס " + txt(code);
  }

  /**
   * ערך נ"ז יחיד, או ``null`` כשאין נתון.
   * ‏0 שהגיע מהשרת הוא **אפס אמיתי**, לא "לא ידוע": חמישה קורסים
   * בתוכנית (‏11063 אנגלית בסיסי, 11064, 11360, 11361, 61179) הם באמת 0 נ"ז,
   * ו-``api.py`` מבחין בעצמו בין הצהרה לבורות (``_stated_credits`` מול
   * ``_known_credits``): לא ידוע מגיע כ-``null`` עם ``credits_text: "—"``, ואפס
   * מוצהר מגיע כ-``0`` עם ``credits_source: "curriculum"``. להפוך כאן 0 למקף
   * היה היפוך כלל המפרט — ולכן נדחים כאן רק לא-מספר וערך שלילי.
   */
  function creditsNumber(value) {
    if (value === null || value === undefined || value === "") return null;
    var n = num(value, null);
    if (n === null || !isFinite(n) || n < 0) return null;
    return n;
  }

  /** נ"ז מרשומת שרת אחת, מנורמלת ל-``number | null``. */
  function creditsFromRecord(rec) {
    return rec && typeof rec === "object" ? creditsNumber(rec.credits) : null;
  }

  /** הראשון מבין השניים שיש לו ערך (שניהם כבר מנורמלים), או ``null``. */
  function pickCredits(preferred, fallback) {
    var v = creditsNumber(preferred);
    return v !== null ? v : creditsNumber(fallback);
  }

  /**
   * נ"ז לקורס, או ``null``, לפי סדר SPEC_MULTIFACULTY §3: תוכנית הלימודים
   * (רשימת הסמסטר) קודמת, ואחריה הרשומה שהשרת החזיר — כולל נ"ז
   * מדף פרטי הקורס בידיעון.
   *
   * ``state.known`` אחרון בכוונה: הוא מטמון מקומי (localStorage) שנזרע גם
   * ממספרים שנכתבו ביד ב-``profile.json``. כשהוא קדם לשרת הוא נעל את
   * הערך הראשון שנשמר — ואז אותו מסך הציג שני סכומים שונים לאותם
   * קורסים, כי ``scheduleCredits`` כן מעדיף את תשובת השרת.
   */
  function creditsOf(code) {
    var s = semesterCourseByCode(code);
    var v = s ? creditsNumber(s.credits) : null;
    if (v !== null) return v;
    var c = courseDataByCode(code);
    v = c ? creditsNumber(c.credits) : null;
    if (v !== null) return v;
    var k = state.known[txt(code)];
    return k ? creditsNumber(k.credits) : null;
  }

  /** "—" לכל נ"ז שאינה ידועה. אף פעם לא "0" במקום חוסר. */
  function fmtCredits(value) {
    var v = creditsNumber(value);
    return v === null ? "—" : fmtNumber(v);
  }

  /** סיכום נ"ז על רשימת קודים: הסכום הידוע, וכמה קורסים אין להם נתון. */
  function creditsSummary(codes) {
    var total = 0;
    var known = 0;
    var unknown = 0;
    (codes || []).forEach(function (code) {
      var v = creditsOf(code);
      if (v === null) unknown++;
      else {
        total += v;
        known++;
      }
    });
    return { total: total, known: known, unknown: unknown };
  }

  /**
   * טקסט הסכום. סכום ששותק על קורסים בלי נתון הוא מספר בטוח ושגוי — ולכן
   * מספר החסרים נאמר לצידו, ולא מוסתר.
   */
  function creditsText(summary, opts) {
    opts = opts || {};
    var head = summary.known ? fmtNumber(summary.total) : "—";
    if (opts.unit) head += ' נ"ז';
    if (!summary.unknown) return head;
    return head + " (" + missingCreditsText(summary.unknown, opts.short) + ")";
  }

  function missingCreditsText(count, short) {
    if (short) return count + " ללא נתון";
    return count === 1 ? "קורס אחד ללא נתון" : count + " קורסים ללא נתון";
  }

  function totalCreditsText(opts) {
    return creditsText(creditsSummary(state.codes), opts);
  }

  /** סגירה טרנזיטיבית של קורסים צמודים סביב קוד אחד. */
  function tiedGroupFor(code) {
    var group = Object.create(null);
    group[txt(code)] = true;

    var families = [];
    runtime.semesterCourses.forEach(function (rec) {
      if (rec.tied_with && rec.tied_with.length) {
        families.push([txt(rec.code)].concat(rec.tied_with.map(txt)));
      }
    });
    runtime.courses.forEach(function (rec) {
      if (rec.tied_with && rec.tied_with.length) {
        families.push([txt(rec.code)].concat(rec.tied_with.map(txt)));
      }
    });
    TIED_FALLBACK.forEach(function (family) {
      families.push(family.slice());
    });

    var changed = true;
    var guard = 0;
    while (changed && guard < 12) {
      changed = false;
      guard++;
      families.forEach(function (family) {
        var touches = family.some(function (x) {
          return group[x];
        });
        if (!touches) return;
        family.forEach(function (x) {
          if (x && !group[x]) {
            group[x] = true;
            changed = true;
          }
        });
      });
    }
    return Object.keys(group);
  }

  function isTied(code) {
    return tiedGroupFor(code).length > 1;
  }

  function tiedFamilies() {
    var out = [];
    var seen = Object.create(null);
    runtime.semesterCourses.forEach(function (rec) {
      if (!rec.tied_with || !rec.tied_with.length) return;
      var family = tiedGroupFor(rec.code).sort();
      var key = family.join(",");
      if (!seen[key]) {
        seen[key] = true;
        out.push(family);
      }
    });
    if (!out.length) {
      TIED_FALLBACK.forEach(function (family) {
        var present = family.filter(function (c) {
          return semesterCourseByCode(c) || state.codes.indexOf(c) !== -1;
        });
        if (present.length > 1) out.push(family.slice());
      });
    }
    return out;
  }

  /* =====================================================================
   * 5א. רשימת ההמלצה של הסמסטר
   *
   * הבחירה בשלב 1 — שנה וסמסטר — היא שקובעת מה מסומן בשלב 2: הקורסים
   * שתוכנית הלימודים ממליצה עליהם בסמסטר הזה מסומנים מראש, וקורס שצריך
   * להשלים מסמסטר קודם מתווסף ידנית דרך תיבת החיפוש.
   *
   * מה שהמערכת *לא* עושה כאן, בכוונה: היא לא יודעת מה כבר נלמד, לא מה
   * עבר ולא מה נכשל, ולכן היא לא מנחשת השלמות ולא מציעה אותן. "מומלץ"
   * פירושו "זה מה שכתוב בתוכנית לסמסטר הזה" — לא "זה מה שמתאים לך".
   * ===================================================================== */

  /**
   * חלופות הדדיות: קורסים שהתוכנית מציעה כמה מהם ובוחרים אחד. סימון
   * אוטומטי של כולם היה מרכיב מערכת שאיש לא לומד, ולכן הם נשארים ריקים
   * עם הסבר. מחזירה טקסט הסבר בעברית, או "" כשהקורס אינו חלופה.
   */
  function alternativeReason(rec) {
    if (!rec) return "";
    // אנגלית/עברית לפי ציון פסיכומטרי או יע"ל. בסמסטר 1 יש שתי רמות
    // אנגלית באותה רשימה, ורק אחת מהן שייכת לסטודנט/ית מסוימים.
    if (rec.placement === true) {
      return "קורס השמה — הרמה נקבעת לפי ציון, ויש לבחור את המתאימה";
    }
    // ‏61179+61180 למי שאין פטור מפיזיקה אקדמית, 61181 למי שיש. אחד מהשניים.
    if (txt(rec.physicsTrack)) {
      return "מסלול פיזיקה — תלוי בפטור, ויש לבחור מסלול אחד";
    }
    return "";
  }

  /**
   * האם ל-``offered`` יש בכלל משמעות. קטלוג ריק מחזיר ``offered: false``
   * לכל שורה, וזה "אין נתונים" — לא "שום קורס לא נפתח". להסיק מזה היה
   * משאיר התקנה טרייה עם רשימה ריקה ובלי הסבר.
   */
  function offeredIsKnown() {
    return runtime.semesterCatalogCount !== null && runtime.semesterCatalogCount > 0;
  }

  /** האם קורס בודד ראוי לסימון אוטומטי. */
  function isRecommendable(rec) {
    if (!rec || !txt(rec.code)) return false; // "קורס כללי", "ספורט" — אין קוד לסמן
    if (alternativeReason(rec)) return false;
    if (offeredIsKnown() && rec.offered === false) return false;
    return true;
  }

  /**
   * הקודים שיסומנו אוטומטית, בסדר שבו התוכנית מונה אותם.
   * קורסים צמודים נבחנים כחבילה: אם חבר אחד נפסל, כל החבילה יוצאת —
   * חצי חבילה היא בדיוק מה שהידיעון דוחה.
   */
  function recommendedCodes() {
    var decided = Object.create(null);
    runtime.semesterCourses.forEach(function (rec) {
      var code = txt(rec.code);
      if (!code || decided[code] !== undefined) return;
      // רק חברים שנמצאים ברשימת הסמסטר הזה: ‏TIED_FALLBACK עלול להביא קוד
      // שאינו בה, ואין לסמן קורס על סמך רשימה שלא מכילה אותו.
      var family = tiedGroupFor(code).filter(function (c) {
        return !!semesterCourseByCode(c);
      });
      if (family.indexOf(code) === -1) family.push(code);
      var ok = family.every(function (c) {
        return isRecommendable(semesterCourseByCode(c));
      });
      family.forEach(function (c) {
        decided[c] = ok;
      });
    });
    return uniq(
      runtime.semesterCourses
        .map(function (rec) {
          return txt(rec.code);
        })
        .filter(function (c) {
          return c && decided[c] === true;
        })
    );
  }

  /** השוואת רשימות קודים לפי סדר — כדי לא לצייר מחדש בלי שינוי. */
  function sameCodes(a, b) {
    if (a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (txt(a[i]) !== txt(b[i])) return false;
    }
    return true;
  }

  /**
   * חיתוך לפי ``limits.max_codes``. חריגה ממנו מחזירה 400 בכל בקשת
   * ‏/api/courses ו-/api/solve, כלומר האפליקציה נראית שבורה לגמרי ולא
   * "קצת עמוסה". מה שנבחר ידנית שורד; ההמלצה נחתכת, ותמיד בחבילות שלמות.
   */
  function capRecommended(rec, manual) {
    var limit = num(runtime.maxCodes, 0);
    var kept = rec.slice();
    var dropped = [];
    while (limit > 0 && kept.length && uniq(kept.concat(manual)).length > limit) {
      var family = tiedGroupFor(kept[kept.length - 1]);
      var before = kept.length;
      kept = kept.filter(function (c) {
        return family.indexOf(c) === -1;
      });
      family.forEach(function (c) {
        if (rec.indexOf(c) !== -1 && dropped.indexOf(c) === -1) dropped.push(c);
      });
      if (kept.length === before) break; // הגנה: חבילה שלא הסירה כלום
    }
    return { recommended: kept, dropped: dropped };
  }

  /**
   * מחילה את רשימת ההמלצה של ``sem`` על הבחירה.
   *
   * נקראת רק מתוך התשובה של ``fetchSemesterCourses``, אחרי שומר
   * ה-``seq.semester`` ואחרי ש-``runtime.semesterCourses`` כבר עודכן.
   * כל יציאה מוקדמת כאן היא הבטחה שנשמרת:
   *   • משיכה חוזרת של אותו סמסטר לא מסמנת מחדש מה שבוטל ידנית;
   *   • מסלול בלי תוכנית לימודים לא מאבד את מה שנבחר בו ביד;
   *   • רק מה שהמערכת סימנה — המערכת מסירה.
   */
  function applyRecommendedDefaults(sem) {
    var target = txt(sem);
    var owned = txt(state.autoSemester);

    // 1. אימוץ בחירה קיימת, פעם אחת בלבד. מצב שנשמר לפני שהתכונה הזאת
    //    הייתה קיימת מגיע בלי מקור לקודים שבו; הוא לא נמחק ולא מוחלף, רק
    //    מקבל שיוך: מה שברשימת ההמלצה נחשב מומלץ, מה שמחוצה לה נחשב ידני,
    //    ומה שההמלצה כוללת ולא סומן נחשב "בוטל" ולא יחזור מעצמו. אף תיבה
    //    לא משנה כאן את מצבה — זה כל העניין.
    //    האימוץ תקף רק לסמסטר שהבחירה השמורה **שייכת** לו. סטודנט/ית
    //    ששמרו בקיץ, ואז בחרו שנה ג' סמסטר א', היו מקבלים אחרת את כל
    //    המלצת סמסטר 5 רשומה כ"בוטלה" ורשימה ריקה — בדיוק ההפך ממה
    //    שביקשו. במקרה כזה הבחירה הישנה נחשבת ידנית, וההמלצה מוחלת עליה.
    var manual = state.manualCodes;
    var claimAsManual = false;
    if (!state.provenanceReady && state.codes.length) {
      if (!target || !runtime.semesterCourses.length) return;
      if (target === txt(runtime.adoptSemester)) {
        var adopted = recommendedCodes();
        var picked = selectedSet();
        setState(
          {
            provenanceReady: true,
            autoSemester: target,
            autoCodes: adopted.slice(),
            autoDropped: adopted.filter(function (c) {
              return picked[c] !== true;
            }),
            manualCodes: state.codes.filter(function (c) {
              return adopted.indexOf(txt(c)) === -1;
            }),
          },
          { solve: false }
        );
        return;
      }
      manual = state.codes.slice();
      claimAsManual = true;
    }

    // 2. אותו סמסטר שכבר הוחל, ועדיין יש לו רשימה — לא נוגעים. זה מה
    //    שמחזיק ביטול ידני גם אחרי רענון מהידיעון, בנייה מחדש, או ניסיון
    //    חוזר אחרי שגיאה.
    //    התנאי על הרשימה אינו קישוט: החלפת **מסלול** אינה משנה את מספר
    //    הסמסטר, ובלעדיו סטודנט/ית שעברו להנדסה אזרחית נשארו עם שישה
    //    קורסי תוכנה מסומנים עד שיחליפו גם שנה או סמסטר.
    if (owned && owned === target && runtime.semesterCourses.length) return;

    // 3. החלפה: ההמלצה החדשה במקום הישנה, והבחירה הידנית נשארת.
    //    בלי רשימה (קיץ, צירוף שאינו בתוכנית, מסלול בלי תוכנית) ההמלצה
    //    ריקה — כלומר מסירים את מה שסימנו, ורק אותו.
    var recommended = [];
    var over = [];
    if (target && runtime.semesterCourses.length) {
      var capped = capRecommended(recommendedCodes(), manual);
      recommended = capped.recommended;
      over = capped.dropped;
    }
    var next = uniq(recommended.concat(manual));
    var nextSemester = recommended.length ? target : "";
    if (
      sameCodes(next, state.codes) &&
      nextSemester === owned &&
      state.provenanceReady &&
      !claimAsManual
    ) {
      return;
    }

    setState({
      codes: next,
      provenanceReady: true,
      manualCodes: manual,
      autoSemester: nextSemester,
      autoCodes: recommended.slice(),
      autoDropped: [],
      activeSchedule: 0,
    });
    if (over.length) {
      toast(
        "אפשר לשבץ עד " + num(runtime.maxCodes, 0) + " קורסים בבת אחת, ולכן לא סומנו: " +
          over.join(", ") + ". אפשר להוסיף אותם אחרי הסרת קורס אחר.",
        "warn"
      );
    }
  }

  /** האם הבחירה הנוכחית שונה מרשימת ההמלצה של הסמסטר. */
  function recommendedChanged() {
    if (!txt(state.autoSemester)) return false;
    return state.autoDropped.length > 0;
  }

  /** "החזרת הרשימה המומלצת" — מבטל את הביטולים הידניים ומסמן מחדש. */
  function restoreRecommended() {
    var target = txt(state.semester);
    if (!target || !runtime.semesterCourses.length) return;
    var capped = capRecommended(recommendedCodes(), state.manualCodes);
    setState({
      codes: uniq(capped.recommended.concat(state.manualCodes)),
      provenanceReady: true,
      autoSemester: target,
      autoCodes: capped.recommended.slice(),
      autoDropped: [],
      activeSchedule: 0,
    });
  }

  /* --- חובת נוכחות (SPEC_V2 §2) ------------------------------------- */

  /** ברירת המחדל היא תמיד "יש חובת נוכחות". הוויתור הוא בחירה מפורשת. */
  function attendanceRequired(code, kind) {
    var byCourse = state.attendance[txt(code)];
    if (!byCourse) return true;
    var value = byCourse[txt(kind)];
    if (value === undefined || value === null) return true;
    return value !== false;
  }

  /** מפתח חסר = חובה, בדיוק כמו בשרת — ולכן "חובה" נשמר כמחיקה. */
  function setAttendance(code, kind, required) {
    var att = deepCopy(state.attendance) || {};
    var c = txt(code);
    var k = txt(kind);
    var byKind = att[c] || {};
    if (required) delete byKind[k];
    else byKind[k] = false;
    if (Object.keys(byKind).length) att[c] = byKind;
    else delete att[c];
    setState({ attendance: att, activeSchedule: 0 });
  }

  /** מה שנשלח ל-/api/solve: רק קורסים שנבחרו, רק ערכים מפורשים. */
  function attendanceBody() {
    var out = {};
    var selected = selectedSet();
    Object.keys(state.attendance).forEach(function (code) {
      if (!selected[code]) return;
      var byKind = state.attendance[code] || {};
      var copy = {};
      Object.keys(byKind).forEach(function (kind) {
        copy[kind] = byKind[kind] !== false;
      });
      if (Object.keys(copy).length) out[code] = copy;
    });
    return out;
  }

  /** סוגי הרכיבים שבהם כובתה חובת הנוכחות בקורס אחד. */
  function optionalKindsOf(code) {
    var byKind = state.attendance[txt(code)] || {};
    return Object.keys(byKind).filter(function (kind) {
      return byKind[kind] === false;
    });
  }

  /** סוגי הרכיבים של קורס, בסדר התצוגה של KIND_ORDER. */
  function kindsOf(course) {
    var kinds = uniq(
      (course.groups || []).map(function (g) {
        return txt(g.kind);
      })
    ).filter(Boolean);
    return kinds.sort(function (a, b) {
      var ka = KIND_ORDER.indexOf(a);
      var kb = KIND_ORDER.indexOf(b);
      if (ka === -1) ka = KIND_ORDER.length;
      if (kb === -1) kb = KIND_ORDER.length;
      if (ka !== kb) return ka - kb;
      return a < b ? -1 : a > b ? 1 : 0;
    });
  }

  /**
   * האם הידיעון עצמו אמר משהו על נוכחות ברכיב הזה, ומה בדיוק.
   * מחזירה את נוסח ההערה, או "" אם אין. הערך לא משנה את ברירת המחדל —
   * הוא רק מאפשר לומר בממשק מאיפה היא הגיעה, ושאפשר לשנות אותה בכל זאת.
   */
  /** רשומת ה-attendance_info של השרת לרכיב אחד, אם הגיעה. */
  function attendanceInfoFor(code, kind) {
    var byCourse = runtime.attendanceInfo[txt(code)];
    if (!byCourse) return null;
    var rec = byCourse[txt(kind)];
    return rec && typeof rec === "object" ? rec : null;
  }

  function attendanceNoteFor(course, kind) {
    var found = "";
    // השרת הוא המקור הסמכותי; הסריקה של ההערות שמתחת היא רק רשת ביטחון.
    var info = attendanceInfoFor(course.code, kind);
    if (info && info.from_yedion === true) {
      return txt(info.note) || txt(info.text);
    }
    (course.groups || []).forEach(function (g) {
      if (found || txt(g.kind) !== txt(kind)) return;
      if (txt(g.attendance_source) === "yedion") {
        found = txt(g.attendance_note) || txt(g.note);
        return;
      }
      if (ATTENDANCE_NOTE_RE.test(txt(g.note))) found = txt(g.note);
    });
    if (!found && course.attendance) {
      var rec = course.attendance[txt(kind)];
      if (rec && typeof rec === "object") {
        if (txt(rec.source) === "yedion" || rec.from_yedion === true) {
          found = txt(rec.note) || txt(rec.text);
        }
      }
    }
    return txt(found).trim();
  }

  function viabilityOf(code, kind, groupId) {
    var v = runtime.solve && runtime.solve.viability;
    if (!v) return { ok: true, reason: "" };
    var byKind = v[txt(code)];
    if (!byKind) return { ok: true, reason: "" };
    var byGroup = byKind[txt(kind)];
    if (!byGroup) return { ok: true, reason: "" };
    var rec = byGroup[txt(groupId)];
    if (rec === undefined || rec === null) return { ok: true, reason: "" };
    if (typeof rec === "boolean") {
      return {
        ok: rec,
        reason: rec ? "" : "בחירה זו משאירה את המערכת בלי פתרון",
      };
    }
    return {
      ok: rec.ok !== false,
      reason: txt(rec.reason || "בחירה זו משאירה את המערכת בלי פתרון"),
    };
  }

  function pinnedGroup(code, kind) {
    var byCourse = state.pinned[txt(code)];
    if (!byCourse) return null;
    var gid = byCourse[txt(kind)];
    return gid === undefined || gid === null ? null : txt(gid);
  }

  function rankOf(code, lecturer) {
    var list = state.ranked[txt(code)];
    if (!Array.isArray(list)) return 0;
    var i = list.indexOf(txt(lecturer));
    return i === -1 ? 0 : i + 1;
  }

  /**
   * עותק של מפת {קוד: ...} עם הקורסים שנבחרו בלבד.
   * רשומה רדומה של קורס שירד מהרשימה נשמרת במצב (‏prunePicks לא מוחק
   * אותה), ולכן כל מי שמדווח או שולח חייב לסנן — אחרת יוצהר על נעיצות
   * שאינן שייכות לשום קורס שעל המסך.
   */
  function pickedFor(map) {
    var selected = selectedSet();
    var out = {};
    Object.keys(map || {}).forEach(function (code) {
      if (selected[txt(code)]) out[code] = deepCopy(map[code]);
    });
    return out;
  }

  function pinCount() {
    var n = 0;
    var picked = pickedFor(state.pinned);
    Object.keys(picked).forEach(function (code) {
      n += Object.keys(picked[code] || {}).length;
    });
    return n;
  }

  function rankedCount() {
    var n = 0;
    var picked = pickedFor(state.ranked);
    Object.keys(picked).forEach(function (code) {
      n += (picked[code] || []).length;
    });
    return n;
  }

  /** קורסים בלי נתוני קבוצות — מ-/api/courses ומ-/api/solve, בלי כפילויות. */
  function notOfferedList() {
    var out = [];
    var seen = Object.create(null);
    var add = function (rec) {
      var code = txt(rec.code);
      if (!code || seen[code]) return;
      seen[code] = true;
      out.push({
        code: code,
        name: txt(rec.name),
        reason: txt(rec.reason || rec.error),
        needs_scrape: rec.needs_scrape === true,
      });
    };
    runtime.notOffered.forEach(add);
    if (runtime.solve) pickList(runtime.solve, ["not_offered"], "code").forEach(add);
    return out;
  }

  function schedules() {
    return runtime.solve ? pickList(runtime.solve, ["schedules"], null) : [];
  }

  function activeSchedule() {
    var list = schedules();
    if (!list.length) return null;
    return list[clamp(state.activeSchedule, 0, list.length - 1)];
  }

  function colorOf(code) {
    var idx = runtime.colors[txt(code)];
    return idx === undefined ? crc32(txt(code).trim()) % PALETTE_SIZE : idx;
  }

  function refreshColorMap() {
    var codes = state.codes.slice();
    runtime.courses.forEach(function (c) {
      codes.push(c.code);
    });
    runtime.colors = buildColorMap(codes);
  }

  function anyBusy() {
    return (
      runtime.solveBusy ||
      runtime.coursesBusy ||
      runtime.reparseBusy ||
      !runtime.ready
    );
  }

  /* =====================================================================
   * 6. משיכת נתונים
   * ===================================================================== */

  function fetchBootstrap() {
    return getJSON("/api/bootstrap")
      .then(function (data) {
        runtime.bootstrap = data;
        runtime.bootstrapError = null;
        runtime.maxCodes = num(data && data.limits ? data.limits.max_codes : null, 0);
        runtime.curriculumAvailable = readCurriculumAvailable(data);
        // רשימת המסלולים. ברירת המחדל היא המסלול שיש לו קובץ תוכנית, כדי
        // שסטודנט/ית תוכנה לא תצטרך לבחור כלום; כל השאר בוחרים "אחר"
        // ומקבלים את הקטלוג המלא במקום רשימה של מחלקה זרה.
        if (Array.isArray(data.programs) && data.programs.length) {
          runtime.programs = data.programs;
          if (!txt(state.program)) {
            state.program = txt(data.curriculum_program) || txt(data.programs[0].id);
          }
        }
        applyBootstrapDefaults(data);
        if (isScrapeRunning(data)) startPolling();
        runtime.ready = true;
        render();
        syncData(true);
        ensureCatalogBrowse();
      })
      .catch(function (err) {
        runtime.bootstrapError = errorText(err);
        runtime.ready = true;
        render();
      });
  }

  function isScrapeRunning(data) {
    if (!data) return false;
    if (data.scrape_running === true) return true;
    return !!(data.scrape && data.scrape.running === true);
  }

  var appliedDefaults = false;

  /** ברירות מחדל מהפרופיל — רק כשאין מצב שמור. */
  function applyBootstrapDefaults(data) {
    if (appliedDefaults) return;
    appliedDefaults = true;

    var defaults = (data && data.defaults) || {};
    var profile = (data && data.profile) || {};
    var student = profile.student || {};
    var prefs = profile.preferences || {};

    var academic =
      txt(defaults.academic_year) ||
      txt(student.academic_year) ||
      txt(data && data.year) ||
      state.academicYear;
    if (academic) state.academicYear = academic;

    // מטמון השמות נבנה תמיד — גם אחרי שחזור — כדי שקורס מסמסטר אחר
    // יוצג בשמו ולא כ"קורס 61753".
    pickList(profile, ["selected_courses"], "code").forEach(function (rec) {
      var code = txt(rec.code);
      if (!code) return;
      var prev = state.known[code] || {};
      state.known[code] = {
        name: txt(rec.name) || prev.name || "",
        credits: pickCredits(creditsFromRecord(rec), prev.credits),
        semester: txt(rec.from_semester) || prev.semester || "",
      };
    });

    if (!runtime.restored) {
      var y = num(defaults.year_of_study, num(student.year_of_study, null));
      if (y !== null) state.studyYear = clamp(Math.round(y), 1, 4);
      var t = txt(defaults.term) || txt(student.term);
      if (t) state.term = t;
      var td = num(defaults.target_days, num(prefs.target_days, null));
      if (td !== null) state.targetDays = clamp(Math.round(td), 2, 6);
      if (defaults.forbid_friday === true || prefs.forbid_friday === true) {
        state.forbidFriday = true;
      }
      var tn = num(defaults.top_n, null);
      if (tn !== null) state.topN = clamp(Math.round(tn), 1, 20);
      var early = num(defaults.earliest, null);
      if (early !== null) state.earliest = early;
      var late = num(defaults.latest, null);
      if (late !== null) state.latest = late;

      // ‏defaults.codes (הבחירה מ-data/profile.json) *אינו* מסמן קורסים.
      // הוא רשימה אישית של סטודנט/ית אחד/ת, והיא כללה גם קורס מסמסטר 4
      // — כך שכל מי שפתח/ה את העמוד קיבל/ה אותו מסומן, ובחירת שנה
      // וסמסטר אחרים לא שינתה זאת. מה שמסמן הוא רשימת ההמלצה של הסמסטר
      // שנבחר, ב-``applyRecommendedDefaults``. השמות מהפרופיל עדיין
      // נשמרים במטמון למעלה, כדי שקורס כזה יוצג בשמו כשמוסיפים אותו.
    }

    var resolved = semesterOf(state.studyYear, state.term);
    // ``defaults.semester`` הוא ``curriculum_semester`` מ-profile.json. בלי
    // תוכנית טעונה הוא מצביע על סמסטר שאינו קיים, והיה שולח
    // /api/semester/5/courses לשוא ומצהיר "סמסטר 5 בתוכנית הלימודים".
    var mayGuess = !runtime.restored && runtime.curriculumAvailable !== false;
    state.semester = resolved || (mayGuess ? txt(defaults.semester) : "");
    saveState();
  }

  function fetchSemesterCourses() {
    var sem = txt(state.semester);
    // הקידום קורה **לפני** הענף של "אין סמסטר", ולא אחריו. מעבר לקיץ הוא
    // בקשה חדשה לכל דבר — "אל תציג סמסטר" — ובלי הקידום תשובה של הסמסטר
    // הקודם שעדיין באוויר הייתה עוברת את השומר ומחילה את ההמלצה שלו על
    // בחירה שכבר עברה הלאה.
    var my = ++seq.semester;
    if (!sem) {
      runtime.semesterCourses = [];
      runtime.semesterError = null;
      runtime.semesterCurriculumAvailable = null;
      runtime.semesterBusy = false;
      // "אין סמסטר בתוכנית" (למשל קיץ) הוא תשובה, לא המתנה.
      runtime.semesterFetched = true;
      // אין סמסטר ⇒ אין המלצה. מסירים את מה שסימנו עבור הסמסטר הקודם,
      // אחרת הקורסים שלו נשארים מסומנים ומוצגים כ"מחוץ לסמסטר הזה".
      applyRecommendedDefaults("");
      render();
      ensureCatalogBrowse();
      return Promise.resolve();
    }
    runtime.semesterBusy = true;
    return getJSON(
      "/api/semester/" + encodeURIComponent(sem) + "/courses" +
        "?program=" + encodeURIComponent(state.program || "")
    )
      .then(function (data) {
        if (my !== seq.semester) return;
        runtime.semesterBusy = false;
        runtime.semesterFetched = true;
        // ‏SPEC §4: השרת אומר במפורש אם יש תוכנית לימודים טעונה. אין דגל —
        // ``null``, והרשימה עצמה מכריעה.
        runtime.semesterCurriculumAvailable = readCurriculumAvailable(data);
        runtime.semesterCourses = pickList(data, ["courses", "items"], "code")
          .map(normalizeSemesterCourse)
          .filter(function (rec) {
            return !!rec.code;
          });
        runtime.semesterError = null;
        runtime.semesterCourses.forEach(function (rec) {
          var prev = state.known[rec.code] || {};
          state.known[rec.code] = {
            name: rec.name || prev.name || "",
            credits: pickCredits(rec.credits, prev.credits),
            semester: sem,
          };
        });
        // מה שהקטלוג יודע, לפני שמסיקים משהו מ-``offered``.
        runtime.semesterCatalogCount = num(
          data && data.fallback ? data.fallback.catalog_count : null,
          null
        );
        // כאן, ולא ב-onYearTermChange: רק עכשיו רשימת הסמסטר החדש בידינו.
        // הפעלה מוקדמת יותר הייתה מסמנת את קורסי הסמסטר *הקודם*.
        applyRecommendedDefaults(sem);
        saveState();
        render();
        ensureCatalogBrowse();
      })
      .catch(function (err) {
        if (my !== seq.semester) return;
        // המשיכה נכשלה — לשכוח את החתימה, אחרת syncData יחשוב שהנתונים
        // כבר בידינו ולא ינסה שוב עד רענון הדף.
        lastSig.semester = null;
        runtime.semesterBusy = false;
        runtime.semesterFetched = true;
        runtime.semesterCurriculumAvailable = null;
        runtime.semesterCourses = [];
        runtime.semesterError = errorText(err);
        render();
        // גם כישלון כזה לא משאיר מסך ריק: עוברים לעיון בקטלוג.
        ensureCatalogBrowse();
      });
  }

  function normalizeSemesterCourse(rec) {
    return {
      code: txt(rec.code),
      name: txt(rec.name),
      credits: creditsFromRecord(rec),
      he: num(rec.he, 0),
      te: num(rec.te, 0),
      ma: num(rec.ma, 0),
      pr: num(rec.pr, 0),
      prereq: Array.isArray(rec.prereq) ? rec.prereq.map(txt) : [],
      tied_with: Array.isArray(rec.tied_with) ? rec.tied_with.map(txt) : [],
      note: txt(rec.note),
      cond: txt(rec.cond),
      // חלופות הדדיות. הרשימה הזאת היא whitelist — שדה שלא נכתב כאן פשוט
      // נעלם, ולכן שני אלה חייבים לנחות יחד עם השינוי ב-api.py.
      placement: rec.placement === true,
      physicsTrack: txt(rec.physics_track),
      offered: rec.offered !== false,
      has_data: rec.has_data === true,
    };
  }

  function fetchCourses() {
    if (!state.codes.length) {
      runtime.courses = [];
      runtime.notOffered = [];
      runtime.coursesError = null;
      runtime.fetching = Object.create(null);
      runtime.sources = Object.create(null);
      runtime.fetchSkipped = [];
      runtime.attendanceInfo = Object.create(null);
      refreshColorMap();
      render();
      return Promise.resolve();
    }
    var my = ++seq.courses;
    runtime.coursesBusy = true;
    // ‏SPEC_V2 §1: כל קוד שאין לו נתונים בזיכרון נמשך עכשיו מהידיעון (בלי התחברות),
    // ולכן השורה שלו בשלב 2 מציגה "טוען נתונים…" עד שהתשובה חוזרת. משיכה כזו
    // לוקחת שנייה-שתיים לקורס, ולכן היא נראית — שקט כאן היה נראה כמו תקיעה.
    var pendingFetch = Object.create(null);
    state.codes.forEach(function (code) {
      var c = txt(code);
      if (c && !courseDataByCode(c)) pendingFetch[c] = true;
    });
    runtime.fetching = pendingFetch;
    render();
    return postJSON("/api/courses", {
      codes: state.codes.slice(),
      semester: state.term,
      year: state.academicYear,
      fetch_missing: true,
    })
      .then(function (data) {
        if (my !== seq.courses) return;
        runtime.coursesBusy = false;
        runtime.fetching = Object.create(null);
        runtime.courses = pickList(data, ["courses", "items"], "code").map(
          normalizeCourse
        );
        runtime.notOffered = pickList(
          data,
          ["not_offered", "notOffered"],
          "code"
        ).map(function (rec) {
          return {
            code: txt(rec.code),
            name: txt(rec.name),
            reason: txt(rec.reason || rec.error),
            needs_scrape: rec.needs_scrape === true,
          };
        });
        runtime.coursesError = null;

        // מאיפה הגיע כל קורס: "db" (היה שמור), "fetched" (נמשך עכשיו),
        // "unavailable" (הידיעון לא נתן) או "skipped" (מכסת המשיכות נגמרה).
        var sources = Object.create(null);
        // המפה הראשית מגיעה מהשרת (``sources``); הרשימות רק ממלאות סיבות.
        var serverSources = data && data.sources;
        if (serverSources && typeof serverSources === "object") {
          Object.keys(serverSources).forEach(function (code) {
            sources[txt(code)] = { source: txt(serverSources[code]), reason: "" };
          });
        }
        runtime.courses.forEach(function (c) {
          sources[c.code] = {
            source: txt(c.source) || txt(sources[c.code] && sources[c.code].source) || "db",
            reason: "",
          };
        });
        runtime.notOffered.forEach(function (rec) {
          sources[rec.code] = {
            source: txt(rec.source) || "unavailable",
            reason: txt(rec.reason),
          };
        });

        // מכסת המשיכות: הקורסים שנדחו לבקשה הבאה. השרת מדווח עליהם גם
        // ב-``not_offered``, אבל שם הסיבה נראית ככישלון — וזו רק המתנה.
        var fetchReport = (data && data.fetch) || {};
        runtime.fetchSkipped = pickList(
          fetchReport.skipped !== undefined ? fetchReport : data,
          ["skipped", "fetch_skipped", "not_fetched"],
          "code"
        )
          .map(function (rec) {
            return { code: txt(rec.code), reason: txt(rec.reason) };
          })
          .filter(function (rec) {
            return !!rec.code;
          });

        var attInfo = data && data.attendance;
        runtime.attendanceInfo =
          attInfo && typeof attInfo === "object" ? attInfo : Object.create(null);
        runtime.fetchSkipped.forEach(function (rec) {
          sources[rec.code] = { source: "skipped", reason: rec.reason };
        });
        runtime.sources = sources;

        runtime.courses.forEach(function (c) {
          var prev = state.known[c.code] || {};
          state.known[c.code] = {
            name: c.name || prev.name || "",
            // השרת קודם למטמון, ולא הפוך: תשובה טרייה חייבת לתקן ערך
            // שנשמר ב-localStorage, אחרת המספר הראשון שנראה אי-פעם קופא לנצח.
            // זהה לכותב שב-``fetchSemesterCourses``.
            credits: pickCredits(c.credits, prev.credits),
            semester: prev.semester || "",
          };
        });
        // ניקוי נעיצות/דירוגים משנה את גוף הבקשה לפותר. בלי חישוב מחדש
        // המסך היה נשאר עם תשובה שנבנתה סביב נעיצה שכבר נמחקה.
        if (prunePicks()) scheduleSolve(0);
        refreshColorMap();
        render();
      })
      .catch(function (err) {
        if (my !== seq.courses) return;
        // אותה סיבה: בלי איפוס החתימה, כשל חד-פעמי אחד היה משאיר את שלב 4
        // ריק לכל אורך הסשן ומצהיר שאין נתונים במסד — בזמן ש-/api/solve
        // עובד מול אותו מסד בדיוק. כל שינוי הבא ינסה למשוך שוב.
        lastSig.courses = null;
        runtime.coursesBusy = false;
        runtime.fetching = Object.create(null);
        runtime.courses = [];
        runtime.coursesError = errorText(err);
        render();
      });
  }

  function normalizeCourse(rec) {
    return {
      code: txt(rec.code),
      name: txt(rec.name),
      credits: creditsFromRecord(rec),
      tied_with: Array.isArray(rec.tied_with) ? rec.tied_with.map(txt) : [],
      freshness: rec.freshness || rec.meta || null,
      warnings: pickList(rec, ["warnings"], null),
      curriculum_semester: txt(rec.curriculum_semester),
      // ‏"db" | "fetched" | "unavailable" — מאיפה הגיעו הנתונים בבקשה הזו.
      source: txt(rec.source),
      attendance:
        rec.attendance && typeof rec.attendance === "object" ? rec.attendance : null,
      groups: pickList(rec, ["groups"], "group_id").map(normalizeGroup),
    };
  }

  function normalizeGroup(rec) {
    return {
      group_id: txt(rec.group_id !== undefined ? rec.group_id : rec.id),
      kind: txt(rec.kind),
      lecturer: txt(rec.lecturer),
      note: txt(rec.note),
      linked_to: Array.isArray(rec.linked_to) ? rec.linked_to.map(txt) : [],
      // ברירת המחדל של חובת הנוכחות אינה נקבעת כאן — היא תמיד "חובה".
      // השדות האלה משמשים רק כדי לומר *מאיפה* הגיעה ברירת המחדל.
      attendance_source: txt(
        rec.attendance_source ||
          (rec.attendance_from_yedion === true ? "yedion" : "")
      ),
      attendance_note: txt(rec.attendance_note),
      meetings: pickList(rec, ["meetings"], null).map(normalizeMeeting),
    };
  }

  function normalizeMeeting(rec) {
    return {
      day: Math.round(num(rec.day, 0)),
      start: toMinutes(rec.start),
      end: toMinutes(rec.end),
      room: txt(rec.room),
      building: txt(rec.building),
      semester: txt(rec.semester),
    };
  }

  /** ניקוי נעיצות ודירוגים שכבר לא קיימים בנתונים. */
  /**
   * ניקוי הבחירות העדינות — נעיצות, דירוג מרצים, חובות נוכחות.
   *
   * ‏**קוד שאינו מסומן אינו נמחק כאן.** מאז שהחלפת שנה/סמסטר מחליפה את
   * רשימת הקורסים, מחיקה לפי "לא מסומן" הייתה משמעותה שהצצה בסמסטר אחר
   * וחזרה מוחקת בשקט נעיצה שנבחרה ביד — עבודה אמיתית שאבדה בלי שנאמר עליה
   * דבר. הרשומות נשארות רדומות, וחוזרות לעצמן כשהקורס נבחר שוב.
   * מה שכן מנוקה: נעיצה על קבוצה שכבר אינה קיימת בנתונים.
   *
   * מה שנשלח לשרת מסונן בנפרד (``buildSolveBody``), ולכן רשומה רדומה אינה
   * מגיעה לחוט ואינה משפיעה על השיבוץ.
   */
  function prunePicks() {
    var changed = false;

    Object.keys(state.pinned).forEach(function (code) {
      var data = courseDataByCode(code);
      if (!data) return; // אין עדיין נתונים — לא נוגעים
      var byKind = state.pinned[code] || {};
      Object.keys(byKind).forEach(function (kind) {
        var gid = txt(byKind[kind]);
        var exists = data.groups.some(function (g) {
          return g.kind === kind && g.group_id === gid;
        });
        if (!exists) {
          delete byKind[kind];
          changed = true;
        }
      });
      if (!Object.keys(byKind).length) {
        delete state.pinned[code];
        changed = true;
      }
    });

    // דירוג מרצים וחובות נוכחות נשמרים גם לקורס שאינו מסומן כרגע: הם
    // תלויים רק בקורס עצמו, ולכן נכונים גם כשחוזרים אליו.

    if (changed) saveState();
    return changed;
  }

  /**
   * נעיצות שהשרת שחרר ‏(``dropped_pins`` מ-/api/solve) — הקבוצה כבר לא קיימת
   * בנתונים. השרת מחזיר אותן במפורש כדי שנמחק אותן מהמצב ונחשב מחדש; בלי זה
   * המסך נתקע על תשובה ריקה שמסבירה נעיצה שכבר לא נמצאת בשום מקום בממשק.
   * מחזירה ‏true אם באמת נמחק משהו — כך אין לולאת חישוב אינסופית.
   */
  function applyDroppedPins(data) {
    var dropped = pickList(data, ["dropped_pins", "droppedPins"], null);
    if (!dropped.length) return false;
    var changed = false;
    var reasons = [];
    dropped.forEach(function (rec) {
      if (!rec || typeof rec !== "object") return;
      var code = txt(rec.code);
      var kind = txt(rec.kind);
      var byKind = state.pinned[code];
      if (!byKind || !Object.prototype.hasOwnProperty.call(byKind, kind)) return;
      delete byKind[kind];
      if (!Object.keys(byKind).length) delete state.pinned[code];
      changed = true;
      var why = txt(rec.reason);
      if (why) reasons.push(why);
    });
    if (!changed) return false;
    saveState();
    // לא למחוק בשקט: הסיבה של השרת נעלמת עם התשובה הבאה.
    toast(reasons.join(" ") || "נעיצה ששוחררה הוסרה מהבחירה.", "warn");
    return true;
  }

  function searchCatalog(query) {
    var q = txt(query).trim();
    runtime.catalogQuery = q;
    if (q.length < 2) {
      runtime.catalogResults = [];
      runtime.catalogError = null;
      runtime.catalogBusy = false;
      renderSearchResults();
      return Promise.resolve();
    }
    var my = ++seq.catalog;
    runtime.catalogBusy = true;
    renderSearchResults();
    return getJSON("/api/catalog/search?q=" + encodeURIComponent(q) + "&limit=25")
      .then(function (data) {
        if (my !== seq.catalog) return;
        runtime.catalogBusy = false;
        runtime.catalogResults = pickList(
          data,
          ["results", "courses", "items", "matches"],
          "code"
        ).map(function (rec) {
          return {
            code: txt(rec.code),
            name: txt(rec.name),
            credits: creditsFromRecord(rec),
            in_curriculum: rec.in_curriculum === true,
            curriculum_semester: txt(
              rec.curriculum_semester !== undefined
                ? rec.curriculum_semester
                : rec.semester
            ),
          };
        });
        runtime.catalogError = null;
        renderSearchResults();
      })
      .catch(function (err) {
        if (my !== seq.catalog) return;
        runtime.catalogBusy = false;
        runtime.catalogResults = [];
        runtime.catalogError = errorText(err);
        renderSearchResults();
      });
  }

  /**
   * ‏SPEC §4 — עיון בקטלוג המלא. זה המסלול של מי שתוכנית המחלקה שלו/ה אינה
   * טעונה: חיפוש לפי שם, קוד או תחילית קוד, ישירות מול ``/api/catalog/browse``.
   * שאילתה ריקה מחזירה את תחילת הקטלוג — כדי שהמסך לעולם לא יהיה ריק.
   */
  function browseCatalog(query) {
    var q = txt(query).trim();
    runtime.browseQuery = q;
    runtime.browseLoaded = true;
    // שאילתה חדשה לא נשפטת לפי כישלון קודם. בלי השורה הזאת
    // שגיאה אחת (400 על תחילית קוד, הפעלה מחדש של השרת) הייתה נועלת
    // את מצב הקטלוג עד רענון הדף.
    runtime.browseError = null;
    var my = ++seq.browse;
    runtime.browseBusy = true;
    renderCatalogBrowse();

    var params = "limit=" + BROWSE_LIMIT;
    // ספרות בלבד = תחילית קוד (כך סטודנטים חושבים על זה). כל השאר = שם.
    // עד 7 ספרות בלבד: זו המגבלה של /api/catalog/browse, ורצף ארוך יותר
    // (הדבקה או טעות הקלדה) צריך להחזיר "לא נמצא" — לא שגיאת 400.
    if (q) params += (/^\d{1,7}$/.test(q) ? "&prefix=" : "&q=") + encodeURIComponent(q);

    return getJSON("/api/catalog/browse?" + params)
      .then(function (data) {
        if (my !== seq.browse) return;
        runtime.browseBusy = false;
        runtime.browseError = null;
        runtime.browseTotal = num(data && (data.total !== undefined ? data.total : data.matched), null);
        runtime.browseResults = pickList(
          data,
          ["results", "courses", "items", "matches", "catalog"],
          "code"
        )
          .map(function (rec) {
            return {
              code: txt(rec.code),
              name: txt(rec.name),
              credits: creditsFromRecord(rec),
              in_curriculum: rec.in_curriculum === true,
              has_data: rec.has_data === true,
              offered: rec.offered !== false,
            };
          })
          .filter(function (rec) {
            return !!rec.code;
          });
        renderCatalogBrowse();
      })
      .catch(function (err) {
        if (my !== seq.browse) return;
        runtime.browseBusy = false;
        runtime.browseResults = [];
        runtime.browseTotal = null;
        runtime.browseError = errorText(err);
        renderCatalogBrowse();
      });
  }

  /** טעינה ראשונה של הקטלוג ברגע שברור שאין רשימת קורסים מהתוכנית. */
  function ensureCatalogBrowse() {
    if (!catalogFallbackActive()) return;
    if (runtime.browseBusy) return;
    // כשהניסיון הקודם נכשל — לנסות שוב. ``browseLoaded`` לבדו היה אומר
    // "כבר ניסינו" גם על ניסיון שהסתיים בשגיאה, והופך תקלה חולפת לקבועה.
    if (runtime.browseLoaded && !runtime.browseError) return;
    browseCatalog(ui.search ? txt(ui.search.value) : "");
  }

  function buildSolveBody() {
    var body = {
      codes: state.codes.slice(),
      semester: state.term,
      year: state.academicYear,
      target_days: state.targetDays,
      // רק לקורסים שנבחרו. ‏prunePicks כבר לא מוחק רשומה של קורס שירד
      // מהרשימה — היא נשארת רדומה כדי לחזור אם הקורס יחזור — ולכן הסינון
      // חייב לקרות כאן, בדיוק כמו ב-attendanceBody.
      pinned: pickedFor(state.pinned),
      ranked: pickedFor(state.ranked),
      blocked: deepCopy(state.blocked),
      forbid_friday: state.forbidFriday === true,
      top_n: state.topN,
      // ‏SPEC_V2 §2. שולחים תמיד: false = ההתנהגות הישנה בדיוק, כל חפיפה נפסלת.
      allow_soft_conflicts: state.allowSoftConflicts === true,
    };
    var attendance = attendanceBody();
    // נשלח רק כשיש מה לומר. מפתח חסר = חובת נוכחות, כמו בשרת.
    if (Object.keys(attendance).length) body.attendance = attendance;
    if (state.earliest !== null && state.earliest !== undefined) {
      body.earliest = state.earliest;
    }
    if (state.latest !== null && state.latest !== undefined) {
      body.latest = state.latest;
    }
    return body;
  }

  function doSolve() {
    if (!state.codes.length) {
      runtime.solve = null;
      runtime.solveError = null;
      runtime.solveBusy = false;
      render();
      return Promise.resolve();
    }
    var my = ++seq.solve;
    runtime.solveBusy = true;
    render();
    return postJSON("/api/solve", buildSolveBody())
      .then(function (data) {
        if (my !== seq.solve) return; // תשובה ישנה — להתעלם
        runtime.solveBusy = false;
        runtime.solve = data;
        runtime.solveError = null;
        if (state.activeSchedule >= schedules().length) {
          state.activeSchedule = 0;
          saveState();
        }
        if (applyDroppedPins(data)) scheduleSolve(0);
        render();
      })
      .catch(function (err) {
        if (my !== seq.solve) return;
        runtime.solveBusy = false;
        runtime.solveError = errorText(err);
        render();
      });
  }

  function scheduleSolve(delay) {
    if (solveTimer) clearTimeout(solveTimer);
    solveTimer = setTimeout(function () {
      solveTimer = null;
      doSolve();
    }, delay === undefined ? SOLVE_DEBOUNCE_MS : delay);
  }

  /** מה כבר נמשך — כדי לא למשוך שוב סתם. */
  var lastSig = { semester: null, courses: null, program: null };

  function syncData(force) {
    if (!runtime.ready) return;
    // גם המסלול, ולא רק הסמסטר: ‏/api/semester/<n>/courses מקבל ``?program=``
    // ומחזיר רשימה ריקה למסלול שאין לו תוכנית. בלי המסלול בחתימה החלפת
    // מסלול לא הייתה מושכת מחדש כלום, והרשימה של המסלול הקודם — כולל מה
    // שסומן ממנה — הייתה נשארת על המסך.
    var semSig = txt(state.semester) + "|" + txt(state.program);
    if (force || semSig !== lastSig.semester) {
      lastSig.semester = semSig;
      fetchSemesterCourses();
    }
    // קבוצות הבחירה תלויות במסלול בלבד, ולכן נמשכות רק כשהוא משתנה.
    if (force || txt(state.program) !== lastSig.program) {
      lastSig.program = txt(state.program);
      runtime.electives = null;
      runtime.electivesFor = "";
      fetchElectives();
    }
    var coursesSig = JSON.stringify([
      state.codes.slice().sort(),
      state.term,
      state.academicYear,
    ]);
    if (force || coursesSig !== lastSig.courses) {
      lastSig.courses = coursesSig;
      fetchCourses();
    }
    scheduleSolve();
  }

  function refreshAllData() {
    lastSig.semester = null;
    lastSig.courses = null;
    getJSON("/api/bootstrap")
      .then(function (data) {
        runtime.bootstrap = data;
        runtime.bootstrapError = null;
        render();
      })
      .catch(function (err) {
        runtime.bootstrapError = errorText(err);
        render();
      });
    syncData(true);
  }

  /* =====================================================================
   * 7. רענון מהידיעון (scrape) ובנייה מחדש (reparse)
   * ===================================================================== */

  var pollTimer = null;

  function startScrape() {
    runtime.scrapeError = null;
    runtime.scrape.log = [];
    runtime.logShown = 0;
    runtime.scrape.running = true;
    runtime.scrape.phase = "starting";
    runtime.scrape.exit_code = null;
    runtime.scrape.summary = "";
    runtime.scrape.done = null;
    runtime.scrape.updated = null;
    runtime.scrape.changed = null;
    // הערכה זמנית עד שהתשובה הראשונה מ-/api/scrape/status מגיעה, כדי ששורת
    // הסיכום תגיד "מרענן N קורסים…" כבר מהרגע הראשון.
    var bootDb = (runtime.bootstrap && runtime.bootstrap.db) || {};
    runtime.scrape.total = num(bootDb.count, state.codes.length || null);
    // ‏SPEC_V2 §4: היומן נשאר מקופל. אין פלט טכני על המסך בלי בקשה מפורשת.
    renderHeader();
    postJSON("/api/scrape/start", {})
      .then(function () {
        startPolling();
      })
      .catch(function (err) {
        // 409 = כבר רצה סריקה. זו לא שגיאה — פשוט מתחילים לעקוב אחריה.
        if (err && err.status === 409) {
          startPolling();
          return;
        }
        runtime.scrape.running = false;
        runtime.scrapeError = errorText(err);
        toast(errorText(err), "error");
        renderHeader();
      });
  }

  function startPolling() {
    if (runtime.polling) return;
    runtime.polling = true;
    pollOnce();
  }

  function stopPolling() {
    runtime.polling = false;
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function pollOnce() {
    if (!runtime.polling) return;
    getJSON("/api/scrape/status")
      .then(function (data) {
        var wasRunning = runtime.scrape.running;
        runtime.scrape = {
          running: data.running === true,
          phase: txt(data.phase),
          log: pickList(data, ["log", "lines"], null),
          exit_code:
            data.exit_code === undefined || data.exit_code === null
              ? null
              : num(data.exit_code, null),
          needs_login: data.needs_login === true,
          message: txt(data.message),
          error: txt(data.error),
          // שדות שורת הסיכום. כולם אופציונליים — מה שחסר פשוט לא נאמר.
          codes: pickList(data, ["codes"], null).map(txt).filter(Boolean),
          total: num(data.total, null),
          done: num(data.done, null),
          updated: num(data.updated, null),
          changed: num(
            data.changed !== undefined ? data.changed : data.changes,
            null
          ),
          summary: txt(data.summary),
        };
        runtime.scrapeError = null;
        render();
        if (runtime.scrape.running) {
          pollTimer = setTimeout(pollOnce, SCRAPE_POLL_MS);
          return;
        }
        stopPolling();
        if (wasRunning) {
          var code = runtime.scrape.exit_code;
          toast(
            runtime.scrape.message ||
              (code === 0 ? "הרענון הסתיים." : "הרענון הסתיים עם שגיאה."),
            code === 0 ? "ok" : "warn"
          );
          refreshAllData();
        }
      })
      .catch(function (err) {
        runtime.scrapeError = errorText(err);
        render();
        pollTimer = setTimeout(pollOnce, SCRAPE_POLL_MS * 2);
      });
  }

  function startReparse() {
    if (runtime.reparseBusy) return;
    runtime.reparseBusy = true;
    runtime.logShown = 0;
    runtime.scrape.log = [];
    runtime.scrape.summary = "";
    // גם כאן היומן נשאר מקופל; מה שנראה הוא שורת הסיכום בכותרת.
    render();
    postJSON("/api/reparse", { semester: state.term, year: state.academicYear })
      .then(function (data) {
        runtime.reparseBusy = false;
        runtime.scrape.log = pickList(data, ["log", "lines"], null);
        runtime.scrape.phase = num(data.exit_code, 1) === 0 ? "done" : "failed";
        runtime.scrape.exit_code = num(data.exit_code, null);
        runtime.scrape.message = txt(data.message);
        runtime.scrape.summary =
          txt(data.message) || "הבנייה מחדש מהקבצים השמורים הסתיימה.";
        runtime.logShown = 0;
        toast(txt(data.message) || "הבנייה מחדש הסתיימה.", "ok");
        refreshAllData();
        render();
      })
      .catch(function (err) {
        runtime.reparseBusy = false;
        toast(errorText(err), "error");
        render();
      });
  }

  /**
   * שורת הסיכום היחידה שמופיעה על המסך בזמן רענון ואחריו (SPEC_V2 §4).
   * כל שאר הפירוט נשאר ביומן המקופל.
   */
  function refreshSummaryText() {
    if (runtime.reparseBusy) return "בונה מחדש מהקבצים השמורים…";
    var sc = runtime.scrape;
    var codes = pickList(sc, ["codes"], null).map(txt).filter(Boolean);
    var total = num(sc.total, codes.length || null);

    if (sc.running === true) {
      var done = num(sc.done, null);
      if (total !== null) {
        return (
          "מרענן " +
          total +
          " קורסים…" +
          (done !== null ? " (" + done + " הושלמו)" : "")
        );
      }
      return "מרענן נתונים מהידיעון…";
    }

    if (txt(sc.summary)) return txt(sc.summary);
    if (sc.exit_code === null || sc.exit_code === undefined) return "";
    if (num(sc.exit_code, 1) === 0) {
      var updated = num(sc.updated, total);
      var changed = num(sc.changed, null);
      var line = updated === null ? "הנתונים עודכנו" : "עודכנו " + updated + " קורסים";
      if (changed !== null) line += ", " + changed + " שינויים";
      return line;
    }
    return txt(sc.message) || "הרענון הסתיים עם שגיאה — הפירוט ביומן.";
  }

  function logLineText(entry) {
    if (entry === null || entry === undefined) return "";
    if (typeof entry === "string") return entry;
    if (typeof entry === "object") {
      var body = txt(entry.line || entry.message || entry.text || entry.msg);
      var when = txt(entry.ts || entry.time || "");
      if (!body) {
        try {
          return JSON.stringify(entry);
        } catch (e) {
          return "";
        }
      }
      return when ? when + "  " + body : body;
    }
    return txt(entry);
  }

  /* =====================================================================
   * 8. חיווט ה-DOM (‏index.html מגדיר את המבנה; כאן רק מחברים אליו)
   * ===================================================================== */

  var ui = {};

  function cacheElements() {
    ui.busy = byId("busy-bar");
    ui.freshDot = byId("freshness-dot");
    ui.freshText = byId("freshness-text");
    ui.freshMeta = byId("freshness-meta");
    ui.btnRefresh = byId("btn-refresh");
    ui.btnReparse = byId("btn-reparse");
    ui.logToggle = byId("btn-log-toggle");
    ui.logClose = byId("btn-log-close");
    ui.log = byId("scrape-log");
    ui.logPhase = byId("scrape-phase");
    ui.logLines = byId("scrape-log-lines");
    ui.refreshSummary = byId("refresh-summary");
    ui.banners = byId("banners");
    ui.toasts = byId("toasts");
    ui.tplBanner = byId("tpl-banner");
    ui.tplToast = byId("tpl-toast");

    ui.selProgram = byId("select-program");
    ui.electives = byId("electives");
    ui.electivesTitle = byId("electives-title");
    ui.electivesRule = byId("electives-rule");
    ui.electivesSource = byId("electives-source");
    ui.electivesGroups = byId("electives-groups");
    ui.selYear = byId("select-year");
    ui.selTerm = byId("select-term");
    ui.semesterSummary = byId("semester-summary");
    ui.yearNote = byId("year-note");

    ui.search = byId("course-search");
    ui.searchResults = byId("course-search-results");
    ui.courseList = byId("course-list");
    ui.creditsTotal = byId("credits-total");
    ui.creditsUnknown = byId("credits-unknown");
    ui.coursesNote = byId("courses-note");
    ui.recommendedRow = byId("recommended-row");
    ui.recommendedNote = byId("recommended-note");
    ui.btnRestoreRecommended = byId("btn-restore-recommended");
    // ‏SPEC §4 — מצב קטלוג. אותה תיבת חיפוש, יעד אחר: כשאין תוכנית לימודים
    // היא מזינה את רשימת הקטלוג שמתחתיה במקום את הרשימה הנפתחת.
    ui.searchPlaceholder = ui.search ? txt(ui.search.getAttribute("placeholder")) : "";
    ui.browseBox = byId("catalog-browse");
    ui.browseNote = byId("catalog-browse-note");
    ui.browseList = byId("catalog-results");
    ui.browseState = byId("catalog-browse-state");

    ui.daysRow = byId("days-buttons");
    ui.dayButtons = ui.daysRow
      ? Array.prototype.slice.call(ui.daysRow.querySelectorAll("[data-days]"))
      : [];
    ui.daysTarget = byId("days-target-label");
    ui.minDays = byId("min-days-label");
    ui.feasibleCount = byId("feasible-count-label");
    ui.daysWarning = byId("days-warning");
    ui.inputEarliest = byId("input-earliest");
    ui.inputLatest = byId("input-latest");
    ui.chkFriday = byId("chk-forbid-friday");
    ui.blockedList = byId("blocked-list");

    ui.lectCourses = byId("lecturer-courses");
    ui.lectNote = byId("lecturers-note");
    ui.btnClearRanking = byId("btn-clear-ranking");
    ui.attendanceNote = byId("attendance-note");
    // הטקסט הקבוע נשמר פעם אחת, כדי שאפשר יהיה להוסיף לו משפט מצב בלי לאבד אותו.
    ui.attendanceNoteBase = ui.attendanceNote
      ? txt(ui.attendanceNote.textContent).replace(/\s+/g, " ").trim()
      : "";

    ui.tabs = byId("schedule-tabs");
    ui.btnPrint = byId("btn-print");
    ui.summary = byId("schedule-summary");
    ui.legend = byId("schedule-legend");
    ui.gridScroll = byId("grid-scroll");
    ui.grid = byId("schedule-grid");
    ui.empty = byId("schedule-empty");
    ui.reasons = byId("infeasible-reasons");
    ui.suggestions = byId("infeasible-suggestions");
    ui.scheduleNote = byId("schedule-note");
    ui.softBox = byId("soft-conflicts");
    ui.softSub = byId("soft-conflicts-sub");
    ui.softList = byId("soft-conflicts-list");

    ui.steps = {
      year: byId("step-year"),
      courses: byId("step-courses"),
      days: byId("step-days"),
      lecturers: byId("step-lecturers"),
      schedule: byId("step-schedule"),
    };
    ui.stepStates = {
      year: byId("step-year-state"),
      courses: byId("step-courses-state"),
      days: byId("step-days-state"),
      lecturers: byId("step-lecturers-state"),
      schedule: byId("step-schedule-state"),
    };
  }

  /**
   * לאן הולכת הקלדה בתיבת החיפוש. במצב קטלוג היא מזינה את רשימת
   * הקטלוג — ואם העיון נכשל בפעם הקודמת מנסים אותו שוב וגם פותחים את
   * הרשימה הנפתחת, כדי שכישלון אחד לא ינעל את מצב הקטלוג לכל הסשן.
   */
  function driveSearchBox(value) {
    if (!catalogFallbackActive()) {
      searchCatalog(value);
      return;
    }
    var wasBroken = catalogBrowseBroken();
    browseCatalog(value);
    if (wasBroken) searchCatalog(value);
  }

  function wireEvents() {
    if (ui.selProgram) {
      ui.selProgram.addEventListener("change", function () {
        setState({ program: txt(ui.selProgram.value), activeSchedule: 0 });
      });
    }
    if (ui.selYear) ui.selYear.addEventListener("change", onYearTermChange);
    if (ui.selTerm) ui.selTerm.addEventListener("change", onYearTermChange);

    if (ui.btnRestoreRecommended) {
      ui.btnRestoreRecommended.addEventListener("click", restoreRecommended);
    }

    if (ui.search) {
      var searchTimer = null;
      ui.search.addEventListener("input", function () {
        var value = ui.search.value;
        if (searchTimer) clearTimeout(searchTimer);
        searchTimer = setTimeout(function () {
          searchTimer = null;
          driveSearchBox(value);
        }, SEARCH_DEBOUNCE_MS);
      });
      ui.search.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") {
          ui.search.value = "";
          driveSearchBox("");
        } else if (ev.key === "Enter") {
          ev.preventDefault();
          if (browseDrivesSearchBox()) {
            var hit = runtime.browseResults[0];
            // במצב קטלוג הרשימה נשארת פתוחה — בוחרים כמה קורסים ברצף.
            if (hit) addCourse(hit.code, hit.name, hit.credits, { keepQuery: true });
            return;
          }
          var first = runtime.catalogResults[0];
          if (first) addCourse(first.code, first.name, first.credits);
        }
      });
    }

    ui.dayButtons.forEach(function (btn) {
      var n = clamp(Math.round(num(btn.dataset.days, 4)), 2, 6);
      btn.dataset.fk = "day-" + n;
      btn.addEventListener("click", function () {
        setState({ targetDays: n, activeSchedule: 0 });
      });
    });

    if (ui.chkFriday) {
      ui.chkFriday.addEventListener("change", function () {
        setState({ forbidFriday: ui.chkFriday.checked, activeSchedule: 0 });
      });
    }
    if (ui.inputEarliest) {
      ui.inputEarliest.addEventListener("change", function () {
        var v = txt(ui.inputEarliest.value);
        setState({ earliest: v ? toMinutes(v) : null, activeSchedule: 0 });
      });
    }
    if (ui.inputLatest) {
      ui.inputLatest.addEventListener("change", function () {
        var v = txt(ui.inputLatest.value);
        setState({ latest: v ? toMinutes(v) : null, activeSchedule: 0 });
      });
    }

    if (false) {
      ui.chkAllowSoft.addEventListener("change", function () {
        setState({
          allowSoftConflicts: true,
          activeSchedule: 0,
        });
      });
    }

    if (ui.btnClearRanking) {
      ui.btnClearRanking.addEventListener("click", function () {
        setState({ ranked: {}, pinned: {}, activeSchedule: 0 });
        toast("הדירוג והנעיצות אופסו.", "ok");
      });
    }

    if (ui.btnRefresh) {
      ui.btnRefresh.addEventListener("click", function () {
        if (runtime.scrape.running) return;
        startScrape();
      });
    }
    if (ui.btnReparse) {
      ui.btnReparse.addEventListener("click", startReparse);
    }
    if (ui.logToggle) {
      ui.logToggle.addEventListener("click", function () {
        var showing = ui.log ? !ui.log.hidden : false;
        setHidden(ui.log, showing);
        ui.logToggle.setAttribute("aria-expanded", showing ? "false" : "true");
      });
    }
    if (ui.logClose) {
      ui.logClose.addEventListener("click", function () {
        setHidden(ui.log, true);
        if (ui.logToggle) ui.logToggle.setAttribute("aria-expanded", "false");
      });
    }
    if (ui.btnPrint) {
      ui.btnPrint.addEventListener("click", function () {
        try {
          window.print();
        } catch (e) {
          /* דפדפן בלי הדפסה — לא נורא */
        }
      });
    }
  }

  function onYearTermChange() {
    var y = clamp(
      Math.round(num(ui.selYear ? ui.selYear.value : state.studyYear, state.studyYear)),
      1,
      4
    );
    var t = txt(ui.selTerm ? ui.selTerm.value : state.term) || state.term;
    setState({
      studyYear: y,
      term: t,
      semester: semesterOf(y, t),
      activeSchedule: 0,
    });
  }

  /* =====================================================================
   * 9. באנרים והודעות חולפות
   * ===================================================================== */

  function bannerNode(kind) {
    if (ui.tplBanner && ui.tplBanner.content) {
      var frag = ui.tplBanner.content.cloneNode(true);
      var node = frag.firstElementChild || frag.querySelector("div");
      if (node) {
        node.className = "banner banner--" + kind;
        return node;
      }
    }
    return el("div", { class: "banner banner--" + kind, attrs: { role: "note" } }, [
      el("span", { class: "banner-icon", attrs: { "aria-hidden": "true" } }),
      el("span", { class: "banner-text" }),
      el("button", { class: "banner-close", attrs: { type: "button", "aria-label": "סגירת ההודעה" }, text: "×" }),
    ]);
  }

  /** באנרים מתמשכים. כל אחד עם מפתח — סגירה משתיקה אותו עד שהמצב משתנה. */
  function renderBanners() {
    if (!ui.banners) return;
    var wanted = [];

    if (runtime.bootstrapError) {
      wanted.push({
        key: "bootstrap-error",
        kind: "error",
        text: "לא ניתן לטעון נתונים מהשרת: " + runtime.bootstrapError,
      });
    }
    if (runtime.coursesError) {
      wanted.push({
        key: "courses-error",
        kind: "error",
        text: "טעינת נתוני הקורסים נכשלה: " + runtime.coursesError,
      });
    }
    if (runtime.solveError) {
      wanted.push({
        key: "solve-error",
        kind: "error",
        text: "חישוב המערכת נכשל: " + runtime.solveError,
      });
    }
    if (runtime.semesterError) {
      wanted.push({
        key: "semester-error",
        kind: "error",
        text: "טעינת קורסי הסמסטר נכשלה: " + runtime.semesterError,
      });
    }

    // ‏SPEC_V2 §3: משיכת הקורסים מהידיעון אינה דורשת התחברות, ולכן זה כבר לא
    // המסלול הרגיל. הבאנר נשאר רק למקרה שהרענון רץ במסלול הדפדפן (--browser)
    // ובכל זאת דיווח שנדרשת הזדהות — שתיקה במצב כזה הייתה משאירה תקוע בלי הסבר.
    if (runtime.scrape.needs_login === true) {
      wanted.push({
        key: "needs-login",
        kind: "warn",
        text:
          "הרענון מדווח שנדרשת התחברות ידנית. בדרך כלל אין בכך צורך — משיכת הנתונים " +
          "מהידיעון פועלת בלי התחברות כלל. אם ההודעה חוזרת, אפשר לפתוח את היומן " +
          "ולראות מה נכשל. העמוד הזה לא מבקש, לא מציג ולא שומר סיסמאות.",
      });
    }

    if (runtime.fetchSkipped.length) {
      var skippedCodes = runtime.fetchSkipped.map(function (rec) {
        return rec.code;
      });
      wanted.push({
        key: "fetch-skipped-" + skippedCodes.join(","),
        kind: "info",
        text:
          "לא כל הקורסים נמשכו בבקשה הזו, כדי לא להעמיס על שרת המכללה: " +
          skippedCodes.join(", ") +
          ". אפשר לבקש את השאר עוד רגע.",
        action: {
          label: "משיכת השאר",
          run: function () {
            retryAllMissing();
          },
        },
      });
    }

    var db = (runtime.bootstrap && runtime.bootstrap.db) || {};
    var staleCodes = pickList(db, ["stale"], null).map(txt).filter(Boolean);
    var failedCodes = pickList(db, ["failed"], null).map(txt).filter(Boolean);
    if (db.any_stale === true || staleCodes.length || failedCodes.length) {
      wanted.push({
        key: "stale-" + staleCodes.join(",") + "|" + failedCodes.join(","),
        kind: "warn",
        text:
          "חלק מהנתונים כבר לא טריים" +
          (staleCodes.length ? " (" + staleCodes.join(", ") + ")" : "") +
          ". מומלץ להריץ “רענון מהידיעון” לפני שמסתמכים על המערכת." +
          (failedCodes.length ? " קורסים שנכשלו: " + failedCodes.join(", ") + "." : ""),
      });
    }

    var s = runtime.solve;
    if (s && s.target_reachable === false && num(s.min_days, null) !== null) {
      wanted.push({
        key: "target-" + state.targetDays + "-" + s.min_days,
        kind: "warn",
        text:
          txt(s.target_message) ||
          state.targetDays +
            " ימים אינם אפשריים עם הקורסים האלה — המינימום הוא " +
            s.min_days,
      });
    }
    if (s && pickList(s, ["tied_missing"], null).length) {
      var missingTied = pickList(s, ["tied_missing"], null).map(txt);
      wanted.push({
        key: "tied-" + missingTied.join(","),
        kind: "warn",
        text:
          "הידיעון רושם את הקורסים האלה כחבילה אחת. חסרים: " +
          missingTied.join(", ") +
          ". יש לסמן את כולם יחד, או להוריד את כולם.",
        action: {
          label: "הוספת הקורסים החסרים",
          run: function () {
            var codes = uniq(state.codes.concat(missingTied));
            // הוספה שעוקפת את toggleCourse, ולכן רושמת את המקור בעצמה:
            // מה שאינו מרשימת ההמלצה הוא ידני, ושורד החלפת סמסטר.
            var manual = state.manualCodes.slice();
            missingTied.forEach(function (c) {
              if (state.autoCodes.indexOf(c) === -1 && manual.indexOf(c) === -1) {
                manual.push(c);
              }
            });
            setState({
              codes: codes,
              manualCodes: manual,
              autoDropped: state.autoDropped.filter(function (x) {
                return missingTied.indexOf(x) === -1;
              }),
              activeSchedule: 0,
            });
          },
        },
      });
    }
    if (s && (s.viability_skipped === true || s.viability_truncated === true)) {
      wanted.push({
        key: "viability-partial",
        kind: "info",
        text:
          "בדיקת המבויים הסתומים בוצעה חלקית בגלל כמות הקבוצות. ייתכן שבחירה " +
          "מסוימת עדיין תוביל למצב בלי פתרון.",
      });
    }

    rebuild(ui.banners, function (box) {
      wanted.forEach(function (item) {
        if (runtime.dismissed[item.key]) return;
        var node = bannerNode(item.kind);
        var textNode = node.querySelector
          ? node.querySelector(".banner-text")
          : null;
        if (textNode) textNode.textContent = item.text;
        else node.appendChild(el("span", { class: "banner-text", text: item.text }));

        if (item.action) {
          var actionBtn = el("button", {
            class: "btn btn-ghost btn-sm",
            attrs: { type: "button" },
            data: { fk: "banner-action-" + item.key },
            text: item.action.label,
            on: { click: item.action.run },
          });
          node.appendChild(actionBtn);
        }

        var closeBtn = node.querySelector
          ? node.querySelector(".banner-close")
          : null;
        if (closeBtn) {
          closeBtn.dataset.fk = "banner-close-" + item.key;
          closeBtn.addEventListener("click", function () {
            runtime.dismissed[item.key] = true;
            renderBanners();
          });
        }
        box.appendChild(node);
      });
    });
  }

  function toast(message, kind) {
    if (!ui.toasts || !txt(message)) return;
    var node = null;
    if (ui.tplToast && ui.tplToast.content) {
      var frag = ui.tplToast.content.cloneNode(true);
      node = frag.firstElementChild || frag.querySelector("div");
    }
    if (!node) {
      node = el("div", { class: "toast" }, [el("span", { class: "toast-text" })]);
    }
    node.className = "toast toast--" + (kind || "info");
    var textNode = node.querySelector ? node.querySelector(".toast-text") : null;
    if (textNode) textNode.textContent = txt(message);
    else node.textContent = txt(message);
    ui.toasts.appendChild(node);
    setTimeout(function () {
      if (node.parentNode) node.parentNode.removeChild(node);
    }, TOAST_MS);
  }

  /* =====================================================================
   * 10. רינדור
   * ===================================================================== */

  function render() {
    renderHeader();
    renderBanners();
    renderYearStep();
    renderCoursesStep();
    renderSearchResults();
    renderCatalogBrowse();
    renderElectives();
    renderDaysStep();
    renderLecturersStep();
    renderScheduleStep();
    renderStepStates();
  }

  /* --- כותרת: טריות, כפתורים, יומן ---------------------------------- */

  function renderHeader() {
    setHidden(ui.busy, !anyBusy());

    var boot = runtime.bootstrap;
    var db = (boot && boot.db) || {};
    var cat = (boot && boot.catalog) || {};

    var dotState = "unknown";
    if (boot) {
      if (!num(db.count, 0)) dotState = "empty";
      else if (db.any_stale === true) dotState = "stale";
      else dotState = "fresh";
    }
    if (ui.freshDot) ui.freshDot.setAttribute("data-state", dotState);

    var ageText =
      txt(db.age_text) || agoHebrew(db.newest || db.updated_at || db.fetched_at);
    if (runtime.bootstrapError) {
      setText(ui.freshText, "אין חיבור לשרת המקומי");
    } else if (!boot) {
      setText(ui.freshText, "בטעינת נתונים…");
    } else if (!num(db.count, 0)) {
      setText(ui.freshText, "אין עדיין נתונים במסד — יש להריץ רענון מהידיעון");
    } else {
      setText(ui.freshText, ageText ? "הנתונים נמשכו " + ageText : txt(db.text));
    }

    var meta = [];
    if (num(db.count, null) !== null) meta.push(db.count + " קורסים");
    var groups = 0;
    runtime.courses.forEach(function (c) {
      groups += c.groups.length;
    });
    if (groups) meta.push(groups + " קבוצות");
    if (num(cat.count, null) !== null) meta.push("קטלוג: " + cat.count);
    if (txt(state.academicYear)) meta.push(txt(state.academicYear));
    setText(ui.freshMeta, meta.join(" · "));

    if (ui.btnRefresh) {
      ui.btnRefresh.disabled = runtime.scrape.running === true;
      ui.btnRefresh.textContent = runtime.scrape.running
        ? "רענון פועל…"
        : "רענון מהידיעון";
    }
    if (ui.btnReparse) ui.btnReparse.disabled = runtime.reparseBusy === true;

    // ‏SPEC_V2 §4: על המסך שורה אחת. השורות הגולמיות נשארות ביומן המקופל.
    var summaryLine = refreshSummaryText();
    setText(ui.refreshSummary, summaryLine);
    setHidden(ui.refreshSummary, !summaryLine);

    var sc = runtime.scrape;
    var phase = txt(sc.message) || PHASE_HE[txt(sc.phase)] || txt(sc.phase) || "ממתין";
    if (runtime.reparseBusy) phase = "בונה מחדש מהקבצים השמורים";
    if (runtime.scrapeError) phase = "שגיאה: " + runtime.scrapeError;
    setText(ui.logPhase, phase);

    // שורות היומן מתווספות בלבד — לא מציירים אותו מחדש בכל רינדור
    var lines = sc.log || [];
    if (ui.logLines) {
      if (lines.length < runtime.logShown) {
        clear(ui.logLines);
        runtime.logShown = 0;
      }
      for (var i = runtime.logShown; i < lines.length; i++) {
        var line = logLineText(lines[i]);
        if (line) ui.logLines.appendChild(el("div", { text: line }));
      }
      if (lines.length !== runtime.logShown) {
        runtime.logShown = lines.length;
        ui.logLines.scrollTop = ui.logLines.scrollHeight;
      }
    }
    // אין כאן פתיחה אוטומטית של היומן: משיכת הנתונים אינה דורשת התחברות,
    // ולכן אין שום שלב שבו הסטודנט/ית *חייב/ת* לראות פלט טכני על המסך.
  }

  /* --- שלב 1: שנה וסמסטר -------------------------------------------- */

  var yearOptionsSig = null;

  function renderProgramSelect() {
    if (!ui.selProgram) return;
    var opts = runtime.programs || [];
    if (!opts.length) {
      // אין רשימה מהשרת (גרסה ישנה) — מסתירים את הפקד ולא מחליטים במקומו.
      ui.selProgram.parentNode.hidden = true;
      return;
    }
    ui.selProgram.parentNode.hidden = false;
    var sig = JSON.stringify(opts);
    if (sig !== programOptionsSig) {
      programOptionsSig = sig;
      clear(ui.selProgram);
      opts.forEach(function (o) {
        ui.selProgram.appendChild(
          el("option", { attrs: { value: txt(o.id) }, text: txt(o.label) || txt(o.id) })
        );
      });
    }
    ui.selProgram.value = txt(state.program) || txt(opts[0] && opts[0].id);
  }

  var programOptionsSig = null;

  function renderYearStep() {
    renderProgramSelect();
    if (!ui.selYear || !ui.selTerm) return;
    var years = yearOptions();
    var terms = termOptions();
    var sig = JSON.stringify([years, terms]);
    if (sig !== yearOptionsSig) {
      yearOptionsSig = sig;
      clear(ui.selYear);
      years.forEach(function (y) {
        ui.selYear.appendChild(
          el("option", { attrs: { value: String(y.value) }, text: y.label })
        );
      });
      clear(ui.selTerm);
      terms.forEach(function (t) {
        ui.selTerm.appendChild(
          el("option", { attrs: { value: t.value }, text: t.label })
        );
      });
    }
    ui.selYear.value = String(state.studyYear);
    ui.selTerm.value = txt(state.term);

    var info = semesterInfo(state.semester);
    var yearLabel = YEAR_LABELS[state.studyYear] || "שנה " + state.studyYear;
    if (curriculumSemesterKnown()) {
      var parts = [
        yearLabel,
        "סמסטר " + txt(state.term),
        "סמסטר " + txt(state.semester) + " בתוכנית הלימודים",
      ];
      if (info && num(info.course_count, 0)) {
        parts.push(info.course_count + " קורסים מומלצים");
      }
      setText(ui.semesterSummary, parts.join(" · "));
      setText(ui.yearNote, "");
    } else if (runtime.curriculumAvailable === false) {
      // אין תוכנית טעונה — הבחירה עצמה תקפה, ואסור לדבר על סמסטר
      // בתוכנית שאינה קיימת.
      setText(ui.semesterSummary, yearLabel + " · סמסטר " + txt(state.term));
      setText(ui.yearNote, FALLBACK_NOTE["no-curriculum"]);
    } else {
      setText(ui.semesterSummary, "אין סמסטר תואם בתוכנית הלימודים");
      setText(
        ui.yearNote,
        txt(runtime.bootstrap && runtime.bootstrap.summer_note) ||
          "לצירוף הזה אין רשימת קורסים בתוכנית. אפשר להוסיף קורסים דרך החיפוש בידיעון."
      );
    }
  }

  /* --- שלב 2: קורסים ------------------------------------------------- */

  function selectedSet() {
    var set = Object.create(null);
    state.codes.forEach(function (c) {
      set[txt(c)] = true;
    });
    return set;
  }

  function toggleCourse(code, checked) {
    var family = tiedGroupFor(code);
    var set = selectedSet();
    var order = state.codes.slice();
    var manual = state.manualCodes.slice();
    var dropped = state.autoDropped.slice();

    family.forEach(function (c) {
      var fromPlan = state.autoCodes.indexOf(c) !== -1;
      if (checked) {
        if (!set[c]) {
          set[c] = true;
          order.push(c);
        }
        // סימון חוזר מבטל את ה"ביטול". קורס שאינו מרשימת ההמלצה נרשם
        // כידני, וזה מה שמאפשר לו לשרוד מעבר לסמסטר אחר — בדיוק המקרה
        // של השלמת קורס מסמסטר קודם.
        dropped = dropped.filter(function (x) {
          return x !== c;
        });
        if (!fromPlan && manual.indexOf(c) === -1) manual.push(c);
      } else {
        delete set[c];
        delete state.pinned[c];
        delete state.ranked[c];
        // ביטול של קורס מומלץ נזכר, אחרת משיכה חוזרת של רשימת הסמסטר
        // הייתה מסמנת אותו שוב ומבטלת את ההחלטה בלי לומר מילה.
        if (fromPlan && dropped.indexOf(c) === -1) dropped.push(c);
        manual = manual.filter(function (x) {
          return x !== c;
        });
      }
    });

    var codes = order.filter(function (c) {
      return set[c];
    });
    if (family.length > 1) {
      toast(
        (checked ? "נוספו יחד: " : "הוסרו יחד: ") + family.join(", ") +
          " — הידיעון רושם אותם כחבילה אחת.",
        "info"
      );
    }
    setState({
      codes: uniq(codes),
      manualCodes: manual,
      autoDropped: dropped,
      activeSchedule: 0,
    });
  }

  /**
   * ‏opts.keepQuery — במצב קטלוג לא מנקים את החיפוש אחרי בחירה: אותה שאילתה
   * משמשת לבחירת כמה קורסים ברצף.
   */
  function addCourse(code, name, credits, opts) {
    opts = opts || {};
    var c = txt(code);
    if (!c) return;
    if (state.codes.indexOf(c) !== -1) return;
    var known = Object.assign({}, state.known);
    known[c] = {
      name: txt(name) || (known[c] && known[c].name) || "",
      credits: pickCredits(credits, known[c] && known[c].credits),
      semester: (known[c] && known[c].semester) || "",
    };
    state.known = known;
    if (!opts.keepQuery) {
      if (ui.search) ui.search.value = "";
      runtime.catalogQuery = "";
      runtime.catalogResults = [];
    }
    toggleCourse(c, true);
  }

  function renderCoursesStep() {
    refreshColorMap();

    if (ui.courseList) {
      rebuild(ui.courseList, function (list) {
        var selected = selectedSet();
        var shown = Object.create(null);

        runtime.semesterCourses.forEach(function (rec) {
          shown[rec.code] = true;
          list.appendChild(courseItem(rec, selected[rec.code] === true, false));
        });

        state.codes
          .filter(function (c) {
            return !shown[txt(c)];
          })
          .forEach(function (code) {
            var known = state.known[txt(code)] || {};
            list.appendChild(
              courseItem(
                {
                  code: txt(code),
                  name: nameOf(code),
                  credits: creditsOf(code),
                  prereq: [],
                  tied_with: [],
                  note: "",
                  fromSemester: txt(known.semester),
                  // במצב קטלוג אין "סמסטר בתוכנית" שאפשר להיות מחוצה לו.
                  fromCatalog: catalogFallbackActive() && !txt(known.semester),
                  in_curriculum: false,
                  offered: true,
                  has_data: !!courseDataByCode(code),
                },
                true,
                true
              )
            );
          });

        // במצב קטלוג ההסבר יושב מתחת, ליד רשימת הקטלוג עצמה — לא כאן.
        if (!list.firstChild && !catalogFallbackActive()) {
          list.appendChild(
            el("p", {
              class: "note",
              text: runtime.ready
                ? "אין קורסים להצגה בסמסטר הזה. אפשר להוסיף קורס דרך תיבת החיפוש."
                : "טוען…",
            })
          );
        }
      });
    }

    // ‏SPEC §3: הסכום לעולם לא מציג 0 לנ"ז שאינה ידועה, ולעולם לא מסתיר
    // בשקט קורסים שאין להם נתון — הם נספרים בשורה שמתחת למספר.
    var credits = creditsSummary(state.codes);
    // בלי קורסים כלל הסכום הוא באמת 0. "—" שמור למצב שבו יש קורסים
    // ואין לאף אחד מהם נ"ז ידועות — שני דברים שונים לגמרי.
    var noneChosen = state.codes.length === 0;
    setText(
      ui.creditsTotal,
      credits.known || noneChosen ? fmtNumber(credits.total) : "—"
    );
    setText(
      ui.creditsUnknown,
      credits.unknown ? "(" + missingCreditsText(credits.unknown) + ")" : ""
    );
    setHidden(ui.creditsUnknown, !credits.unknown);

    renderRecommendedRow();

    if (ui.coursesNote) {
      var notes = [];
      tiedFamilies().forEach(function (family) {
        notes.push(
          "הידיעון רושם את " +
            family.join(", ") +
            " כחבילה אחת: סימון של אחד מסמן את כולם, וביטול של אחד מבטל את כולם."
        );
      });
      if (!catalogFallbackActive()) {
        notes.push(
          "אפשר להוסיף כל קורס אחר מהידיעון דרך תיבת החיפוש — כולל חזרה על קורס מסמסטר קודם, שהוא מקרה רגיל לגמרי."
        );
      }
      setText(ui.coursesNote, notes.join(" "));
    }
  }

  /**
   * שורת ההמלצה: מה סומן מראש בעקבות הבחירה בשלב 1, ומה עושים כשצריך
   * להשלים קורס מסמסטר קודם. מוסתרת לגמרי במצב קטלוג ובקיץ — שם אין
   * רשימת המלצה, ומשפט שמדבר עליה היה מצהיר על משהו שאינו קיים.
   */
  function renderRecommendedRow() {
    if (!ui.recommendedRow) return;
    var sem = txt(state.autoSemester);
    var show = !catalogFallbackActive() && !!sem && runtime.semesterCourses.length > 0;
    setHidden(ui.recommendedRow, !show);
    setHidden(ui.btnRestoreRecommended, !show || !recommendedChanged());
    if (!show) {
      setText(ui.recommendedNote, "");
      return;
    }

    // ‏"N קורסים מתוך התוכנית" ולא "N הקורסים שהתוכנית ממליצה עליהם":
    // בסמסטר 1 התוכנית מונה עשרה, ומהם סומנו חמישה — השאר הם חלופות
    // ושורות בלי קוד. הניסוח השני היה מצהיר על מספר שאיש לא אמר.
    var parts = [
      "סומנו מראש " + state.autoCodes.length +
        " קורסים מתוך תוכנית הלימודים לסמסטר " + sem + ".",
    ];
    var alternatives = runtime.semesterCourses.filter(function (rec) {
      return !!alternativeReason(rec);
    });
    if (alternatives.length) {
      parts.push("קורסי חלופה — השמה או מסלול פיזיקה — לא סומנו, ויש לבחור את המתאים.");
    }
    if (state.autoDropped.length) {
      parts.push("בוטלו: " + state.autoDropped.join(", ") + ".");
    }
    parts.push(
      "צריך להשלים קורס מסמסטר קודם? אפשר לחפש אותו בתיבה שלמעלה ולהוסיף אותו לרשימה."
    );
    setText(ui.recommendedNote, parts.join(" "));
  }

  /**
   * מצב הנתונים של קורס אחד — התשובה לשאלה "למה כתוב שאין נתונים במסד?".
   * מחזירה {state, tag, tagClass, text, retry}. אף מצב אינו שקט לגמרי:
   * לכל אחד יש הסבר, ולכל מצב חסום יש כפתור ניסיון חוזר.
   */
  function courseStatus(code, selected, hasDataHint) {
    var c = txt(code);
    var have = !!courseDataByCode(c);
    var src = runtime.sources[c] || null;
    var name = src ? txt(src.source) : "";
    var reason = src ? txt(src.reason) : "";

    if (!have && (runtime.fetching[c] || (selected && (runtime.coursesBusy || !runtime.ready)))) {
      return {
        state: "loading",
        tag: "טוען נתונים…",
        tagClass: "",
        text: "טוען נתונים מהידיעון — זה לוקח שנייה-שתיים ואינו דורש התחברות.",
        retry: false,
      };
    }
    if (name === "unavailable") {
      return {
        state: "unavailable",
        tag: "אין נתונים",
        tagClass: "tag--warn",
        text:
          (reason ||
            "הידיעון לא החזיר נתוני קבוצות לקורס הזה — ייתכן שהוא אינו נפתח בסמסטר הזה.") +
          " אפשר לנסות שוב, או להסיר את הקורס מהבחירה.",
        retry: true,
      };
    }
    if (name === "skipped") {
      return {
        state: "skipped",
        tag: "נדחה לרגע",
        tagClass: "tag--warn",
        text:
          (reason ||
            "הקורס לא נמשך בבקשה הזו כדי לא להעמיס על שרת המכללה (עד 12 משיכות בכל פעם).") +
          " אפשר לנסות שוב עוד רגע.",
        retry: true,
      };
    }
    if (have) {
      return name === "fetched"
        ? {
            state: "fetched",
            tag: "נמשך מהידיעון עכשיו",
            tagClass: "",
            text: "",
            retry: false,
          }
        : { state: "ready", tag: "", tagClass: "", text: "", retry: false };
    }
    if (!selected) {
      if (hasDataHint) return { state: "ready", tag: "", tagClass: "", text: "", retry: false };
      return {
        state: "none",
        tag: "אין נתונים עדיין",
        tagClass: "tag--warn",
        text: "הנתונים של הקורס עדיין לא נמשכו. סימון הקורס ימשוך אותם מהידיעון אוטומטית, בלי התחברות.",
        retry: false,
      };
    }
    return {
      state: "pending",
      tag: "אין נתונים",
      tagClass: "tag--warn",
      text: "אין עדיין נתוני קבוצות לקורס הזה. אפשר לבקש משיכה נוספת מהידיעון.",
      retry: true,
    };
  }

  function retryButton(code, label) {
    return el("button", {
      class: "btn btn-ghost btn-sm",
      attrs: { type: "button", title: "ניסיון נוסף למשוך את הקורס מהידיעון" },
      data: { fk: "retry-" + txt(code) },
      text: label || "ניסיון חוזר",
      on: {
        click: function (ev) {
          // הכרטיס עצמו הוא <label>; בלי העצירה הזו הלחיצה הייתה גם מבטלת סימון.
          ev.preventDefault();
          ev.stopPropagation();
          retryFetch(code);
        },
      },
    });
  }

  /** משיכה חוזרת לקורס אחד: מאפסים את החתימה כדי ש-fetchCourses ירוץ שוב. */
  function retryFetch(code) {
    var c = txt(code);
    if (c) {
      delete runtime.sources[c];
      runtime.fetching[c] = true;
    }
    runtime.fetchSkipped = runtime.fetchSkipped.filter(function (rec) {
      return rec.code !== c;
    });
    lastSig.courses = null;
    render();
    fetchCourses();
  }

  function retryAllMissing() {
    runtime.fetchSkipped = [];
    state.codes.forEach(function (code) {
      var c = txt(code);
      if (c && !courseDataByCode(c)) {
        delete runtime.sources[c];
        runtime.fetching[c] = true;
      }
    });
    lastSig.courses = null;
    render();
    fetchCourses();
  }

  /**
   * כרטיס קורס אחד.
   * ‏opts.onToggle — מי שמטפל בסימון במקום ``toggleCourse`` (שורת קטלוג
   * צריכה גם לשמור שם ונ"ז). ‏opts.quiet — בלי פסקת ההסבר על מצב הנתונים,
   * לרשימות ארוכות שבהן היא הייתה הופכת לרעש.
   */
  function courseItem(rec, checked, isExtra, opts) {
    opts = opts || {};
    var code = txt(rec.code);
    var unavailable = rec.offered === false;
    // חלופה שלא סומנה אוטומטית. בלי ההסבר הזה הסטודנט/ית רואים שלוש
    // שורות אנגלית ריקות ולא יודעים אם זו תקלה או כוונה.
    var altReason = isExtra ? "" : alternativeReason(rec);

    var box = el("input", {
      attrs: { type: "checkbox" },
      data: { fk: "course-" + code },
      on: {
        change: function (ev) {
          if (opts.onToggle) opts.onToggle(ev.target.checked === true);
          else toggleCourse(code, ev.target.checked);
        },
      },
    });
    box.checked = checked === true;
    box.disabled = unavailable && !checked;

    var main = el("div", { class: "course-main" }, [
      el("span", { class: "course-name", text: txt(rec.name) }),
      el("span", { class: "course-code", text: code }),
    ]);

    var hours = [];
    if (num(rec.he, 0)) hours.push("הרצאה " + fmtNumber(rec.he));
    if (num(rec.te, 0)) hours.push("תרגול " + fmtNumber(rec.te));
    if (num(rec.ma, 0)) hours.push("מעבדה " + fmtNumber(rec.ma));
    if (num(rec.pr, 0)) hours.push("פרויקט " + fmtNumber(rec.pr));
    // ‏SPEC §3: "—" ולא "0" — 86% מהקטלוג אינו בתוכנית, ואין לו נ"ז שמורות.
    var meta = [fmtCredits(rec.credits) + ' נ"ז'];
    if (hours.length) meta.push(hours.join(" · "));
    if (rec.prereq && rec.prereq.length) meta.push("קדם: " + rec.prereq.join(", "));
    main.appendChild(el("span", { class: "course-meta", text: meta.join(" | ") }));
    if (txt(rec.note)) {
      main.appendChild(el("span", { class: "course-meta", text: txt(rec.note) }));
    }
    if (altReason) {
      main.appendChild(el("span", { class: "course-meta", text: altReason }));
    }

    var tags = el("div", { class: "course-tags" });
    if (rec.fromCatalog) {
      tags.appendChild(
        el("span", {
          class: "tag " + (rec.in_curriculum ? "tag--in-plan" : "tag--out-plan"),
          text: rec.in_curriculum ? "בתוכנית הלימודים" : "מהקטלוג",
        })
      );
    } else if (isExtra) {
      tags.appendChild(
        el("span", {
          class: "tag tag--out-plan",
          text: rec.fromSemester
            ? "מסמסטר " + rec.fromSemester + " בתוכנית"
            : "מחוץ לסמסטר הזה",
        })
      );
    } else {
      tags.appendChild(
        el("span", { class: "tag tag--in-plan", text: "בתוכנית-סמסטר " + txt(state.semester) })
      );
    }
    if (isTied(code)) {
      tags.appendChild(el("span", { class: "tag tag--tied", text: "קורס צמוד" }));
    }
    if (altReason) {
      tags.appendChild(el("span", { class: "tag tag--warn", text: "חלופה — לבחירה ידנית" }));
    }
    if (unavailable) {
      tags.appendChild(el("span", { class: "tag tag--dead", text: "לא נפתח בסמסטר" }));
    }

    // ‏SPEC_V2 §1: אף קורס לא נשאר עם "אין נתונים" בלי הסבר ובלי דרך קדימה.
    var status = unavailable
      ? { state: "ready", tag: "", tagClass: "", text: "", retry: false }
      : courseStatus(code, checked === true, rec.has_data === true);
    if (status.tag) {
      tags.appendChild(
        el("span", {
          class: "tag" + (status.tagClass ? " " + status.tagClass : ""),
          text: status.tag,
        })
      );
    }
    if (tags.firstChild) main.appendChild(tags);
    // ברשימת הקטלוג נשארת רק התגית הקצרה: ההסבר המלא וכפתור הניסיון החוזר
    // מופיעים בכרטיס של הקורס הנבחר למעלה, וכפילות שלהם היא רעש.
    if (status.text && !opts.quiet) {
      main.appendChild(
        el("span", {
          class: "course-meta",
          attrs: { role: status.state === "loading" ? "status" : null },
          text: status.text,
        })
      );
    }
    if (status.retry && !opts.quiet) main.appendChild(retryButton(code));

    var cls = "course-item";
    if (checked) cls += " is-selected";
    if (isTied(code)) cls += " is-tied";
    if (unavailable) cls += " is-unavailable";

    // ‏<label> — לחיצה בכל מקום בכרטיס מחליפה את תיבת הסימון, בלי כפל אירועים.
    return el(
      "label",
      {
        class: cls,
        attrs: { title: unavailable ? "הקורס לא נפתח בסמסטר הזה" : "" },
        style: { "--course-idx": String(colorOf(code)) },
      },
      [box, main]
    );
  }

  function renderSearchResults() {
    if (!ui.searchResults) return;
    // במצב קטלוג אותה תיבה מזינה את רשימת הקטלוג שמתחת, ולכן אין רשימה נפתחת.
    if (browseDrivesSearchBox()) {
      clear(ui.searchResults);
      setHidden(ui.searchResults, true);
      return; // תפקיד התיבה מתעדכן ב-renderCatalogBrowse
    }
    var results = runtime.catalogResults;
    // הרשימה נפתחת בזמן שיש חיפוש פעיל — גם כדי להראות "מחפש…" או "לא נמצאו".
    var show = !!runtime.catalogQuery;

    rebuild(ui.searchResults, function (box) {
      if (!runtime.catalogQuery) return;
      if (runtime.catalogBusy) {
        box.appendChild(el("li", { text: "מחפש…" }));
        return;
      }
      if (runtime.catalogError) {
        box.appendChild(el("li", { text: "החיפוש נכשל: " + runtime.catalogError }));
        return;
      }
      if (!results.length) {
        box.appendChild(el("li", { text: "לא נמצאו קורסים מתאימים." }));
        return;
      }
      var selected = selectedSet();
      results.forEach(function (rec) {
        var already = selected[rec.code] === true;
        var tag = rec.in_curriculum
          ? "[בתוכנית" +
            (rec.curriculum_semester ? "-סמסטר " + rec.curriculum_semester : "") +
            "]"
          : "[מחוץ לתוכנית]";
        var li = el(
          "li",
          {
            attrs: {
              role: "option",
              "aria-selected": already ? "true" : "false",
              tabindex: "0",
            },
            data: { fk: "hit-" + rec.code },
            on: {
              click: function () {
                if (!already) addCourse(rec.code, rec.name, rec.credits);
              },
              keydown: function (ev) {
                if (ev.key === "Enter" || ev.key === " ") {
                  ev.preventDefault();
                  if (!already) addCourse(rec.code, rec.name, rec.credits);
                }
              },
            },
          },
          [
            el("span", { class: "course-code", text: rec.code }),
            el("span", { class: "course-name", text: txt(rec.name) }),
            el("span", {
              class: "tag " + (rec.in_curriculum ? "tag--in-plan" : "tag--out-plan"),
              text: tag,
            }),
          ]
        );
        if (already) {
          li.appendChild(el("span", { class: "tag", text: "כבר נבחר" }));
        }
        box.appendChild(li);
      });
    });

    setHidden(ui.searchResults, !show);
    if (ui.search) {
      ui.search.setAttribute("aria-expanded", show ? "true" : "false");
    }
  }

  /* --- שלב 2, מצב קטלוג: בחירה מהקטלוג המלא (SPEC §4) ---------------- */

  /**
   * הרשימה שמחליפה את קורסי התוכנית כשאין תוכנית טעונה.
   * שני המצבים חיים זה לצד זה: כשיש תוכנית, כל זה נשאר מוסתר והרשימה
   * הרגילה אינה משתנה כלל.
   */

  // ======================================================================
  // קבוצות קורסי בחירה (אשכולות / מסלולי התמחות) מפרק השנתון של המסלול
  // ======================================================================
  function fetchElectives() {
    var program = txt(state.program);
    if (!program || program === "other") {
      runtime.electives = { available: false };
      runtime.electivesFor = program;
      return Promise.resolve();
    }
    if (runtime.electivesFor === program && runtime.electives) return Promise.resolve();
    runtime.electivesFor = program;
    runtime.electivesBusy = true;
    var my = ++seq.electives;
    return getJSON("/api/program/electives?program=" + encodeURIComponent(program))
      .then(function (data) {
        if (my !== seq.electives) return; // תשובה ישנה — מתעלמים
        runtime.electivesBusy = false;
        runtime.electives = data || { available: false };
        render();
      })
      .catch(function () {
        if (my !== seq.electives) return;
        runtime.electivesBusy = false;
        // כישלון רשת אינו "אין אשכולות" — מסתירים, ולא ממציאים.
        runtime.electives = { available: false };
        runtime.electivesFor = "";
        render();
      });
  }

  function renderElectives() {
    if (!ui.electives) return;
    var data = runtime.electives;
    var show = !!(data && data.available);
    setHidden(ui.electives, !show);
    if (!show) return;

    var isTracks = data.structure === "tracks";
    var groups = (isTracks ? data.tracks : data.clusters) || {};
    setText(
      ui.electivesTitle,
      isTracks ? "מסלולי התמחות" : "אשכולות קורסי בחירה"
    );
    // הכלל אינו קוסמטי: אשכול = אחד מכל קבוצה, מסלול = בוחרים מסלול אחד.
    setText(ui.electivesRule, txt(isTracks ? data.track_rule : data.cluster_rule));
    // שנה מוצגת תמיד — גם כשהמסמך לא ציין אותה, ואז נאמר בדיוק את זה.
    setText(
      ui.electivesSource,
      "מקור: פרק השנתון של " + txt(data.program) + " · " + txt(data.year_text)
    );

    rebuild(ui.electivesGroups, function (box) {
      var selected = selectedSet();
      Object.keys(groups).forEach(function (name) {
        var courses = groups[name] || [];
        var wrap = el("div", { class: "electives-group" });
        wrap.appendChild(
          el("h4", {
            class: "electives-group-title",
            text: name + " (" + courses.length + ")",
          })
        );
        var list = el("div", { class: "course-list" });
        courses.forEach(function (course) {
          var code = txt(course.code);
          var chosen = selected[code] === true;
          var row = el("label", { class: "course-row" + (chosen ? " is-selected" : "") });
          var box2 = el("input", { attrs: { type: "checkbox" } });
          box2.checked = chosen;
          box2.addEventListener("change", function () {
            if (box2.checked) addCourse(code, course.name, null, { keepQuery: true });
            else toggleCourse(code, false);
          });
          row.appendChild(box2);
          row.appendChild(el("span", { class: "course-code", text: code }));
          row.appendChild(el("span", { class: "course-name", text: txt(course.name) }));
          list.appendChild(row);
        });
        wrap.appendChild(list);
        box.appendChild(wrap);
      });
    });
  }

  function renderCatalogBrowse() {
    var reason = catalogFallbackReason();
    var active = reason !== "";

    var drives = browseDrivesSearchBox();
    setHidden(ui.browseBox, !active);
    if (ui.search) {
      ui.search.setAttribute(
        "placeholder",
        drives ? BROWSE_PLACEHOLDER : txt(ui.searchPlaceholder)
      );
      // ‏combobox פירושו רשימה נפתחת. כשהתיבה מזינה רשימה קבועה שמתחתיה
      // אין רשימה נפתחת — ולכן גם התפקיד הנגיש משתנה.
      ui.search.setAttribute("role", drives ? "searchbox" : "combobox");
      ui.search.setAttribute(
        "aria-controls",
        drives ? "catalog-results" : "course-search-results"
      );
      if (drives) ui.search.removeAttribute("aria-expanded");
    }
    if (!active) return;

    var note = FALLBACK_NOTE[reason] || FALLBACK_NOTE["empty-semester"];
    if (catalogBrowseBroken()) note += " החיפוש בקטלוג לא זמין — אפשר להוסיף קורס בתיבת החיפוש שלמעלה.";
    setText(ui.browseNote, note);

    if (ui.browseList) {
      rebuild(ui.browseList, function (list) {
        if (runtime.browseError) {
          list.appendChild(
            el("p", { class: "note", text: "החיפוש בקטלוג נכשל: " + runtime.browseError })
          );
          return;
        }
        if (!runtime.browseResults.length) {
          list.appendChild(
            el("p", {
              class: "note",
              text: runtime.browseBusy
                ? "טוען מהקטלוג…"
                : runtime.browseQuery
                ? "לא נמצא קורס מתאים בקטלוג."
                : "הקטלוג ריק — יש להריץ רענון מהידיעון.",
            })
          );
          return;
        }
        var selected = selectedSet();
        runtime.browseResults.forEach(function (rec) {
          list.appendChild(catalogItem(rec, selected[rec.code] === true));
        });
      });
    }

    var bits = [];
    if (runtime.browseResults.length) {
      bits.push("מוצגים " + runtime.browseResults.length + " קורסים");
      if (
        runtime.browseTotal !== null &&
        runtime.browseTotal > runtime.browseResults.length
      ) {
        bits.push("מתוך " + runtime.browseTotal + " — אפשר לצמצם בחיפוש");
      }
    }
    setText(ui.browseState, bits.join(" "));
  }

  /** שורת קטלוג אחת — אותו כרטיס בדיוק, עם שמירת השם והנ"ז בבחירה. */
  function catalogItem(rec, checked) {
    return courseItem(
      {
        code: rec.code,
        name: rec.name,
        credits: rec.credits,
        prereq: [],
        tied_with: [],
        note: "",
        offered: rec.offered !== false,
        has_data: rec.has_data === true,
        fromCatalog: true,
        in_curriculum: rec.in_curriculum === true,
      },
      checked,
      false,
      {
        quiet: true,
        onToggle: function (on) {
          if (on) addCourse(rec.code, rec.name, rec.credits, { keepQuery: true });
          else toggleCourse(rec.code, false);
        },
      }
    );
  }

  /* --- שלב 3: ימי לימוד ---------------------------------------------- */

  function renderDaysStep() {
    var s = runtime.solve || {};
    var minDays = num(s.min_days, null);

    ui.dayButtons.forEach(function (btn) {
      var n = num(btn.dataset.days, 0);
      btn.setAttribute("aria-checked", n === state.targetDays ? "true" : "false");
      // יעד שנמוך מהמינימום האפשרי מסומן — אבל נשאר לחיץ, כי הוא רק העדפה.
      setClass(btn, "is-impossible", minDays !== null && n < minDays);
      btn.setAttribute(
        "title",
        minDays !== null && n < minDays
          ? n + " ימים אינם אפשריים עם הקורסים האלה — המינימום הוא " + minDays
          : ""
      );
    });

    setText(ui.daysTarget, state.targetDays + " ימים");
    setText(ui.minDays, minDays === null ? "—" : minDays + " ימים");
    setText(
      ui.feasibleCount,
      runtime.solve ? String(num(s.feasible_count, 0)) : "—"
    );
    setClass(
      ui.minDays && ui.minDays.parentNode,
      "fact--warn",
      s.target_reachable === false
    );

    if (ui.daysWarning) {
      if (s.target_reachable === false && minDays !== null) {
        setText(
          ui.daysWarning,
          txt(s.target_message) ||
            state.targetDays +
              " ימים אינם אפשריים עם הקורסים האלה — המינימום הוא " +
              minDays
        );
        setHidden(ui.daysWarning, false);
      } else {
        setHidden(ui.daysWarning, true);
        setText(ui.daysWarning, "");
      }
    }

    if (ui.chkFriday) ui.chkFriday.checked = state.forbidFriday === true;
    if (ui.inputEarliest && document.activeElement !== ui.inputEarliest) {
      ui.inputEarliest.value =
        state.earliest === null ? "" : fmtTime(state.earliest);
    }
    if (ui.inputLatest && document.activeElement !== ui.inputLatest) {
      ui.inputLatest.value = state.latest === null ? "" : fmtTime(state.latest);
    }

    if (ui.blockedList) {
      rebuild(ui.blockedList, function (box) {
        state.blocked.forEach(function (win, i) {
          var day = Math.round(num(win[0], 0));
          var label =
            "יום " +
            dayLetter(day) +
            "׳ " +
            fmtTime(win[1]) +
            "–" +
            fmtTime(win[2]);
          box.appendChild(
            el("button", {
              class: "tag",
              attrs: { type: "button", title: "הסרת החסימה" },
              data: { fk: "blocked-" + i },
              text: label + " ✕",
              on: {
                click: function () {
                  var next = state.blocked.slice();
                  next.splice(i, 1);
                  setState({ blocked: next, activeSchedule: 0 });
                },
              },
            })
          );
        });
      });
    }
  }

  /* --- שלב 4: מרצים -------------------------------------------------- */

  function sortedGroups(course) {
    return course.groups.slice().sort(function (a, b) {
      var ka = KIND_ORDER.indexOf(a.kind);
      var kb = KIND_ORDER.indexOf(b.kind);
      if (ka === -1) ka = KIND_ORDER.length;
      if (kb === -1) kb = KIND_ORDER.length;
      if (ka !== kb) return ka - kb;
      return a.group_id < b.group_id ? -1 : a.group_id > b.group_id ? 1 : 0;
    });
  }

  function toggleLecturer(code, lecturer) {
    var name = txt(lecturer);
    if (!name) return;
    var ranked = deepCopy(state.ranked);
    var list = Array.isArray(ranked[code]) ? ranked[code].slice() : [];
    var i = list.indexOf(name);
    if (i === -1) list.push(name);
    else list.splice(i, 1);
    if (list.length) ranked[code] = list;
    else delete ranked[code];
    setState({ ranked: ranked, activeSchedule: 0 });
  }

  function togglePin(code, kind, groupId) {
    var pinned = deepCopy(state.pinned);
    var byKind = pinned[code] || {};
    if (txt(byKind[kind]) === txt(groupId)) delete byKind[kind];
    else byKind[kind] = txt(groupId);
    if (Object.keys(byKind).length) pinned[code] = byKind;
    else delete pinned[code];
    setState({ pinned: pinned, activeSchedule: 0 });
  }

  function renderLecturersStep() {
    if (ui.btnClearRanking) {
      ui.btnClearRanking.disabled = rankedCount() === 0 && pinCount() === 0;
    }

    if (ui.lectCourses) {
      rebuild(ui.lectCourses, function (box) {
        if (!state.codes.length) {
          box.appendChild(
            el("p", { class: "note", text: "יש לסמן קורסים בשלב 2 כדי לראות את הקבוצות." })
          );
          return;
        }

        var missing = notOfferedList();
        var explained = Object.create(null);
        missing.forEach(function (rec) {
          explained[rec.code] = true;
        });
        if (missing.length) {
          var warnBox = el("div", { class: "lect-course" }, [
            el("div", { class: "lect-course-head" }, [
              el("span", { class: "lect-course-title", text: "קורסים בלי נתוני קבוצות" }),
            ]),
          ]);
          missing.forEach(function (rec) {
            var line = el("div", { class: "field-row" }, [
              el("span", {
                class: "note",
                text:
                  rec.code +
                  " " +
                  (rec.name || nameOf(rec.code)) +
                  " — " +
                  (rec.reason ||
                    "הידיעון לא החזיר נתוני קבוצות לקורס הזה בסמסטר הנוכחי."),
              }),
              retryButton(rec.code, "ניסיון חוזר מהידיעון"),
            ]);
            warnBox.appendChild(line);
          });
          box.appendChild(warnBox);
        }

        state.codes.forEach(function (code) {
          var course = courseDataByCode(code);
          if (!course) {
            if (explained[txt(code)]) return;
            var st = courseStatus(code, true, false);
            var wrap = el("div", { class: "field-row" }, [
              el("span", {
                class: "note",
                text:
                  code +
                  " " +
                  nameOf(code) +
                  " — " +
                  (st.text || "טוען נתונים מהידיעון…"),
              }),
            ]);
            if (st.retry) wrap.appendChild(retryButton(code, "ניסיון חוזר מהידיעון"));
            box.appendChild(wrap);
            return;
          }
          box.appendChild(coursePanel(course));
        });
      });
    }

    renderAttendanceNote();

    if (ui.lectNote) {
      var bits = [];
      if (rankedCount()) bits.push(rankedCount() + " מרצים מדורגים");
      if (pinCount()) bits.push(pinCount() + " קבוצות נעוצות");
      setText(
        ui.lectNote,
        bits.length
          ? bits.join(" · ") + ". כל שינוי כאן מחשב את המערכת מחדש מיד."
          : "אפשר לדלג על השלב הזה — בלי העדפות המנוע בוחר לפי הימים והחורים בלבד."
      );
    }
  }

  /**
   * המשפט שמתחת למתג הכללי. הוא לא מחליף את ההסבר הקבוע שב-index.html אלא
   * מוסיף לו את המצב הנוכחי — כדי שלא ייווצר מצב שבו מתג דלוק ושום דבר לא קורה.
   */
  function renderAttendanceNote() {
    if (!ui.attendanceNote) return;
    var off = [];
    runtime.courses.forEach(function (course) {
      var kinds = kindsOf(course);
      optionalKindsOf(course.code).forEach(function (kind) {
        if (kinds.indexOf(kind) !== -1) off.push(course.code + " " + kind);
      });
    });

    var extra = "";
    if (off.length) {
      extra = " ללא חובת נוכחות: " + off.join(", ") + ".";
    }
    setText(ui.attendanceNote, txt(ui.attendanceNoteBase) + extra);
  }

  function coursePanel(course) {
    var code = course.code;
    var idx = colorOf(code);

    var metaBits = [fmtCredits(creditsOf(code)) + ' נ"ז', course.groups.length + " קבוצות"];
    var fresh = course.freshness || {};
    if (txt(fresh.age_text)) {
      metaBits.push((fresh.stale === true ? "נתונים ישנים · " : "") + txt(fresh.age_text));
    }
    var ranked = state.ranked[code] || [];
    if (ranked.length) {
      metaBits.push(
        "עדיפות: " +
          ranked
            .map(function (name, i) {
              return i + 1 + ". " + name;
            })
            .join(" · ")
      );
    }

    var head = el("div", { class: "lect-course-head" }, [
      el("span", { class: "legend-chip c" + idx, text: code }),
      el("span", { class: "lect-course-title", text: txt(course.name) }),
      el("span", { class: "lect-course-meta", text: metaBits.join(" · ") }),
    ]);

    var panel = el("section", { class: "lect-course" }, [head]);

    var warnings = pickList(course, ["warnings"], null)
      .map(function (w) {
        return txt(typeof w === "object" ? w.text || w.message : w);
      })
      .filter(Boolean);
    warnings.forEach(function (w) {
      panel.appendChild(el("p", { class: "note", text: w }));
    });

    panel.appendChild(attendanceBox(course));

    var table = el("table", { class: "lect-table" }, [
      el("thead", {}, [
        el("tr", {}, [
          el("th", { text: "קבוצה" }),
          el("th", { text: "סוג" }),
          el("th", { text: "מרצה" }),
          el("th", { text: "יום" }),
          el("th", { text: "שעות" }),
          el("th", { text: "חדר" }),
          el("th", { text: "נעיצה" }),
        ]),
      ]),
    ]);
    var tbody = el("tbody");
    sortedGroups(course).forEach(function (group) {
      tbody.appendChild(groupRow(course, group));
    });
    table.appendChild(tbody);
    panel.appendChild(el("div", { class: "lect-table-wrap" }, [table]));
    return panel;
  }

  /**
   * מתג "חובת נוכחות" לכל סוג רכיב בקורס. ברירת המחדל דלוקה תמיד; כיבוי
   * מאפשר למנוע — יחד עם המתג הכללי — לשבץ את הרכיב במקביל לרכיב אחר.
   */
  function attendanceBox(course) {
    var code = course.code;
    var box = el("div", { class: "lect-attendance" });
    var row = el("div", { class: "field-row" });
    var hints = [];

    kindsOf(course).forEach(function (kind) {
      var input = el("input", {
        attrs: { type: "checkbox" },
        data: { fk: "att-" + code + "-" + kind },
        on: {
          change: function (ev) {
            setAttendance(code, kind, ev.target.checked === true);
          },
        },
      });
      input.checked = attendanceRequired(code, kind);
      row.appendChild(
        el(
          "label",
          {
            class: "field field-check",
            attrs: {
              title:
                "כשאין חובת נוכחות, המנוע רשאי לשבץ את הרכיב הזה במקביל לרכיב אחר — " +
                "בתנאי שהמתג הכללי למעלה דלוק.",
            },
          },
          [input, el("span", { text: "חובת נוכחות · " + kind })]
        )
      );

      var note = attendanceNoteFor(course, kind);
      if (note) {
        hints.push(
          kind + ": הידיעון כותב “" + note + "”. לכן ברירת המחדל כאן היא חובת נוכחות — " +
            "ועדיין אפשר לשנות אותה ידנית."
        );
      }
    });

    box.appendChild(row);
    hints.forEach(function (hint) {
      box.appendChild(el("p", { class: "note", text: hint }));
    });

    var off = optionalKindsOf(code).filter(function (kind) {
      return kindsOf(course).indexOf(kind) !== -1;
    });
    if (off.length) {
      box.appendChild(
        el("p", {
          class: "note",
          text:
            "ללא חובת נוכחות: " +
            off.join(", ") +
            (state.allowSoftConflicts
              ? " — המנוע רשאי לשבץ אותם במקביל לרכיב אחר, וכל חפיפה כזו תוצג בשלב 5."
              : " — כדי שחפיפה אכן תותר יש להדליק גם את המתג הכללי שלמעלה."),
        })
      );
    }
    return box;
  }

  function groupRow(course, group) {
    var code = course.code;
    var gid = group.group_id;
    var kind = group.kind;
    var isPinned = pinnedGroup(code, kind) === gid;
    var via = viabilityOf(code, kind, gid);
    var dead = via.ok === false && !isPinned;
    var rank = rankOf(code, group.lecturer);

    var cls = "";
    if (rank) cls += " is-ranked";
    if (isPinned) cls += " is-pinned";
    if (dead) cls += " is-dead";

    var tr = el("tr", {
      class: cls.replace(/^ /, ""),
      attrs: {
        title: dead
          ? via.reason
          : isPinned
          ? "קבוצה נעוצה — לחיצה על “נעוץ” משחררת"
          : txt(group.lecturer)
          ? "לחיצה " + (rank ? "מסירה את" : "מוסיפה את") + " " + group.lecturer + " מסדר העדיפויות"
          : "",
        "aria-disabled": dead ? "true" : null,
      },
      data: { fk: "row-" + code + "-" + kind + "-" + gid },
      on: {
        click: function () {
          if (dead) return;
          toggleLecturer(code, group.lecturer);
        },
      },
    });

    // קבוצה
    var idCell = el("td", { class: "cell-group" }, [el("span", { text: gid })]);
    if (group.note) {
      idCell.appendChild(el("div", { class: "course-meta", text: group.note }));
    }
    if (group.linked_to && group.linked_to.length) {
      // רשימה ארוכה מרחיבה את הטבלה בלי צורך — מציגים אחת ומספר, והשאר בתיאור.
      var linked = group.linked_to;
      var linkedText =
        linked.length <= 2
          ? linked.join(", ")
          : linked[0] + " ועוד " + (linked.length - 1);
      idCell.appendChild(
        el("div", {
          class: "course-meta cell-group",
          attrs: { title: "קבוצות מקושרות: " + linked.join(", ") },
          text: "משויכת ל-" + linkedText,
        })
      );
    }
    tr.appendChild(idCell);

    tr.appendChild(el("td", { text: kind }));

    // מרצה + תג הדירוג
    var lectCell = el("td");
    if (rank) {
      lectCell.appendChild(el("span", { class: "rank-badge", text: String(rank) }));
    }
    lectCell.appendChild(
      el("span", { text: txt(group.lecturer) || "מרצה לא ידוע" })
    );
    tr.appendChild(lectCell);

    // יום / שעות / חדר — שורה לכל מפגש
    var dayCell = el("td");
    var timeCell = el("td", { class: "cell-time" });
    var roomCell = el("td");
    if (!group.meetings.length) {
      dayCell.appendChild(el("div", { text: "—" }));
      timeCell.appendChild(el("div", { text: "ללא מפגשים" }));
      roomCell.appendChild(el("div", { text: "—" }));
    }
    group.meetings.forEach(function (m) {
      dayCell.appendChild(el("div", { text: dayLetter(m.day) + "׳" }));
      timeCell.appendChild(
        el("div", { text: fmtTime(m.start) + "–" + fmtTime(m.end) })
      );
      roomCell.appendChild(
        el("div", { text: [m.building, m.room].filter(Boolean).join(" ") || "—" })
      );
    });
    tr.appendChild(dayCell);
    tr.appendChild(timeCell);
    tr.appendChild(roomCell);

    // נעיצה — כפתור נפרד; הלחיצה עליו לא מדרגת מרצה
    var pinBtn = el("button", {
      class: "pin-btn",
      attrs: {
        type: "button",
        "aria-pressed": isPinned ? "true" : "false",
        title: dead ? via.reason : isPinned ? "שחרור הנעיצה" : "נעיצת הקבוצה הזו",
      },
      data: { fk: "pin-" + code + "-" + kind + "-" + gid },
      text: isPinned ? "נעוץ ✓" : "נעיצה",
      on: {
        click: function (ev) {
          ev.stopPropagation();
          if (dead) return;
          togglePin(code, kind, gid);
        },
      },
    });
    pinBtn.disabled = dead;
    var pinCell = el("td", {}, [pinBtn]);
    if (dead) {
      pinCell.appendChild(el("div", { class: "course-meta", text: via.reason }));
    }
    tr.appendChild(pinCell);

    return tr;
  }

  /* --- שלב 5: המערכת ------------------------------------------------- */

  function renderScheduleStep() {
    var s = runtime.solve;
    var list = schedules();
    var feasible = s ? num(s.feasible_count, list.length) : null;
    var infeasible = !!s && list.length === 0;

    // לשוניות
    if (ui.tabs) {
      rebuild(ui.tabs, function (box) {
        list.forEach(function (sch, idx) {
          box.appendChild(
            el("button", {
              class: "tab",
              attrs: {
                type: "button",
                role: "tab",
                "aria-selected": idx === state.activeSchedule ? "true" : "false",
              },
              data: { fk: "tab-" + idx },
              text:
                "מערכת " +
                (idx + 1) +
                " · " +
                num(sch.days_count, 0) +
                " ימים · חורים " +
                fmtSpan(sch.gap_minutes),
              on: {
                click: function () {
                  setState({ activeSchedule: idx }, { solve: false });
                },
              },
            })
          );
        });
      });
    }

    var sch = activeSchedule();
    // ‏SPEC_V2 §2: חפיפה מכוונת אף פעם לא עוברת בשקט. היא מדווחת מעל הרשת,
    // ומסומנת גם בתוך הרשת עצמה.
    var soft = sch ? softConflictInfo(sch) : null;
    renderSoftConflicts(soft);

    // סיכום
    if (ui.summary) {
      rebuild(ui.summary, function (box) {
        if (!sch) return;
        var days = Array.isArray(sch.days)
          ? sch.days.slice()
          : uniq(
              scheduleMeetings(sch).map(function (m) {
                return m.day;
              })
            );
        days.sort(function (a, b) {
          return a - b;
        });
        box.appendChild(fact("ניקוד", fmtNumber(sch.score)));
        box.appendChild(
          fact(
            "ימים",
            num(sch.days_count, days.length) +
              " (" +
              days
                .map(function (d) {
                  return dayLetter(d);
                })
                .join(" ") +
              ")"
          )
        );
        box.appendChild(fact("חורים", fmtSpan(sch.gap_minutes)));
        box.appendChild(fact('נ"ז', creditsText(scheduleCredits(sch), { short: true })));
        if (num(sch.lecturer_total, 0) > 0) {
          box.appendChild(
            fact(
              "מרצים מועדפים",
              num(sch.lecturer_hits, 0) + "/" + num(sch.lecturer_total, 0)
            )
          );
        }
        var breakdown = sch.breakdown || {};
        Object.keys(breakdown).forEach(function (k) {
          box.appendChild(
            fact(BREAKDOWN_HE[k] || k, fmtNumber(breakdown[k]))
          );
        });
      });
    }

    // מקרא הצבעים
    if (ui.legend) {
      rebuild(ui.legend, function (box) {
        if (!sch) return;
        var seen = Object.create(null);
        pickList(sch, ["picks"], null).forEach(function (p) {
          var code = txt(p.code);
          if (seen[code]) return;
          seen[code] = true;
          box.appendChild(
            el("span", {
              class: "legend-chip c" + colorOf(code),
              text: code + " " + (txt(p.name) || nameOf(code)),
            })
          );
        });
      });
    }

    // הרשת
    if (ui.grid) {
      rebuild(ui.grid, function (box) {
        if (!sch) return;
        buildGrid(box, sch, soft);
      });
    }
    setHidden(ui.gridScroll, !sch);

    // אין פתרון
    if (ui.empty) {
      setHidden(ui.empty, !infeasible);
      if (infeasible) {
        if (ui.reasons) {
          rebuild(ui.reasons, function (box) {
            var reasons = pickList(s, ["reasons"], null);
            if (!reasons.length) {
              box.appendChild(
                el("li", { text: "השרת לא החזיר הסבר מפורט." })
              );
            }
            reasons.forEach(function (r) {
              box.appendChild(
                el("li", {
                  text: txt(typeof r === "object" ? r.text || r.reason : r),
                })
              );
            });
          });
        }
        if (ui.suggestions) {
          rebuild(ui.suggestions, function (box) {
            pickList(s, ["suggestions"], null).forEach(function (r) {
              box.appendChild(
                el("li", { text: txt(typeof r === "object" ? r.text || r.tip : r) })
              );
            });
            if (pinCount() > 0) {
              box.appendChild(
                el("li", {}, [
                  el("button", {
                    class: "btn btn-ghost btn-sm",
                    attrs: { type: "button" },
                    data: { fk: "unpin-all" },
                    text: "שחרור כל הנעיצות",
                    on: {
                      click: function () {
                        setState({ pinned: {}, activeSchedule: 0 });
                        toast("כל הנעיצות שוחררו.", "ok");
                      },
                    },
                  }),
                ])
              );
            }
          });
        }
      }
    }

    // הערה מתחת לרשת
    if (ui.scheduleNote) {
      var note = "";
      if (!state.codes.length) {
        note = "יש לסמן לפחות קורס אחד בשלב 2.";
      } else if (runtime.solveBusy && !s) {
        note = "מחשב…";
      } else if (runtime.solveError) {
        note = "החישוב נכשל: " + runtime.solveError;
      } else if (s && !infeasible) {
        note =
          "נמצאו " +
          feasible +
          " מערכות אפשריות; מוצגות " +
          list.length +
          " המובילות." +
          (s.counts_truncated === true
            ? " הספירה נעצרה במכסה — ייתכן שיש עוד."
            : "") +
          (num(s.elapsed_ms, null) !== null
            ? " (חישוב: " + num(s.elapsed_ms, 0) + " מ״ש)"
            : "");
      }
      setText(ui.scheduleNote, note);
    }
  }

  /**
   * ‏"ניקוד: -68.2". המחלקה ltr קיימת ב-style.css בדיוק בשביל זה: בלעדיה
   * המינוס של מספר שלילי מודבק בסוף ("68.2-") בגלל כיוון הכתיבה.
   */
  function fact(label, value) {
    return el("span", { class: "fact" }, [
      el("span", { class: "fact-label", text: label }),
      el("strong", { class: "fact-value ltr", text: txt(value) }),
    ]);
  }

  /** סיכום נ"ז למערכת אחת, כולל ספירת הקורסים שאין להם נתון. */
  function scheduleCredits(sch) {
    var seen = Object.create(null);
    var total = 0;
    var known = 0;
    var unknown = 0;
    pickList(sch, ["picks"], null).forEach(function (p) {
      var code = txt(p.code);
      if (seen[code]) return;
      seen[code] = true;
      var v = pickCredits(creditsFromRecord(p), creditsOf(code));
      if (v === null) unknown++;
      else {
        total += v;
        known++;
      }
    });
    return { total: total, known: known, unknown: unknown };
  }

  /** כל המפגשים של מערכת אחת, שטוחים, עם פרטי הקורס. */
  function scheduleMeetings(sch) {
    var out = [];
    pickList(sch, ["picks"], null).forEach(function (pick) {
      var code = txt(pick.code);
      pickList(pick, ["meetings"], null).forEach(function (raw) {
        var m = normalizeMeeting(raw);
        out.push({
          code: code,
          name: txt(pick.name) || nameOf(code),
          kind: txt(pick.kind),
          group_id: txt(pick.group_id),
          lecturer: txt(pick.lecturer),
          day: m.day,
          start: m.start,
          end: m.end,
          room: [m.building, m.room].filter(Boolean).join(" "),
        });
      });
    });
    return out.sort(function (a, b) {
      return a.day - b.day || a.start - b.start;
    });
  }

  /**
   * הרשת השבועית, בדיוק לפי החוזה שב-index.html:
   *   עמודה 1 = שעות (יושבת מימין בזכות dir=rtl), ימים א..ו = עמודות day+1,
   *   שורה 1 = כותרות, וכל שורה נוספת = 15 דקות.
   */
  /** מפתח יציב למפגש בודד בתוך מערכת אחת. */
  function meetingKey(m) {
    return m.code + "|" + m.group_id + "|" + m.day + "|" + m.start + "|" + m.end;
  }

  function meetingSide(m) {
    return (
      m.code +
      " " +
      m.kind +
      " קב' " +
      m.group_id +
      " (יום " +
      dayLetter(m.day) +
      "׳ " +
      fmtTime(m.start) +
      "–" +
      fmtTime(m.end) +
      ")"
    );
  }

  function meetingShort(m) {
    return m.code + " " + m.kind + " קב' " + m.group_id;
  }

  function softConflictLine(a, b) {
    var optional = [];
    if (!attendanceRequired(a.code, a.kind)) optional.push(a.code + " " + a.kind);
    if (!attendanceRequired(b.code, b.kind)) optional.push(b.code + " " + b.kind);
    var tail = optional.length
      ? " — נבחר בהנחה שאין חובת נוכחות ב-" + optional.join(" וב-") + "."
      : " — יש לוודא שאפשר לוותר על הנוכחות באחד מהשניים.";
    return "חפיפה מכוונת: " + meetingSide(a) + " מול " + meetingSide(b) + tail;
  }

  /**
   * החפיפות בתוך מערכת אחת.
   *
   * הזיהוי נעשה כאן מהמפגשים עצמם, ולא רק מהשדה שהשרת שולח: בלוק שחופף בפועל
   * חייב להיראות חופף ברשת, גם אם הדיווח מהשרת חסר או בפורמט אחר. נוסח הדיווח
   * מגיע מ-``soft_conflict_report`` כשהוא קיים, ואחרת נבנה כאן.
   */
  function softConflictInfo(sch) {
    var meetings = scheduleMeetings(sch);
    var pairs = [];
    var marks = Object.create(null);
    var minutes = 0;

    for (var i = 0; i < meetings.length; i++) {
      for (var j = i + 1; j < meetings.length; j++) {
        var a = meetings[i];
        var b = meetings[j];
        if (a.day !== b.day) continue;
        if (a.start >= b.end || b.start >= a.end) continue;
        if (a.code === b.code && a.group_id === b.group_id) continue;
        pairs.push([a, b]);
        minutes += Math.min(a.end, b.end) - Math.max(a.start, b.start);
        var ka = meetingKey(a);
        var kb = meetingKey(b);
        marks[ka] = marks[ka] ? marks[ka] + ", " + meetingShort(b) : meetingShort(b);
        marks[kb] = marks[kb] ? marks[kb] + ", " + meetingShort(a) : meetingShort(a);
      }
    }

    var lines = [];
    var report = sch.soft_conflict_report;
    if (typeof report === "string") {
      // הדיווח מהשרת עשוי להימשך על כמה שורות מוזחות; מאחדים אותן לפריט אחד.
      report.split("\n").forEach(function (raw) {
        var line = txt(raw);
        if (!line.trim()) return;
        if (/^\s/.test(line) && lines.length) {
          lines[lines.length - 1] += " " + line.trim();
        } else {
          lines.push(line.trim());
        }
      });
    } else if (report) {
      lines = asList(report, null)
        .map(function (rec) {
          return txt(
            rec && typeof rec === "object"
              ? rec.text || rec.line || rec.message || rec.reason
              : rec
          ).trim();
        })
        .filter(Boolean);
    }
    if (!lines.length) {
      lines = pairs.map(function (pair) {
        return softConflictLine(pair[0], pair[1]);
      });
    }

    var reported = num(sch.soft_conflicts, null);
    return {
      count: reported === null ? pairs.length : Math.max(reported, pairs.length),
      pairs: pairs,
      marks: marks,
      lines: lines,
      minutes: num(sch.soft_conflict_minutes, minutes),
    };
  }

  /** הדיווח מעל הרשת. לעולם לא בפינה, ולעולם לא מקופל. */
  function renderSoftConflicts(info) {
    if (!ui.softBox) return;
    var show = !!info && info.count > 0 && info.lines.length > 0;
    setHidden(ui.softBox, !show);
    if (!show) {
      setText(ui.softSub, "");
      if (ui.softList) clear(ui.softList);
      return;
    }
    var head =
      (info.count === 1
        ? "במערכת הזו יש חפיפה מכוונת אחת"
        : "במערכת הזו יש " + info.count + " חפיפות מכוונות") +
      " — שני רכיבים באותו זמן. זה התאפשר רק משום שסומן שאין חובת נוכחות באחד הצדדים, " +
      "ומשמעותו ויתור בפועל על הנוכחות באחד מהם.";
    if (info.minutes > 0) {
      head += " סך זמן החפיפה: " + fmtSpan(info.minutes) + " שעות.";
    }
    setText(ui.softSub, head);
    rebuild(ui.softList, function (box) {
      info.lines.forEach(function (line) {
        box.appendChild(el("li", { text: line }));
      });
    });
  }

  /**
   * חלוקת רוחב למפגשים חופפים באותו יום.
   * ‏CSS Grid מצייר שני פריטים באותו תא זה על גבי זה, ואז אחד מהם פשוט נעלם —
   * וזה בדיוק המידע שאסור להסתיר. לכן כל אשכול חופף מתחלק ל"נתיבים".
   */
  function assignLanes(meetings) {
    var out = Object.create(null);
    var byDay = Object.create(null);
    meetings.forEach(function (m) {
      var key = String(m.day);
      if (!byDay[key]) byDay[key] = [];
      byDay[key].push(m);
    });

    Object.keys(byDay).forEach(function (key) {
      var list = byDay[key].slice().sort(function (a, b) {
        return a.start - b.start || a.end - b.end;
      });
      var cluster = [];
      var clusterEnd = -1;

      var flush = function () {
        if (!cluster.length) return;
        var laneEnds = [];
        var placed = [];
        cluster.forEach(function (m) {
          var lane = 0;
          while (lane < laneEnds.length && laneEnds[lane] > m.start) lane++;
          laneEnds[lane] = m.end;
          placed.push({ m: m, lane: lane });
        });
        placed.forEach(function (rec) {
          out[meetingKey(rec.m)] = { lane: rec.lane, lanes: laneEnds.length };
        });
        cluster = [];
        clusterEnd = -1;
      };

      list.forEach(function (m) {
        if (cluster.length && m.start >= clusterEnd) flush();
        cluster.push(m);
        clusterEnd = Math.max(clusterEnd, m.end);
      });
      flush();
    });
    return out;
  }

  function buildGrid(root, sch, soft) {
    var meetings = scheduleMeetings(sch);
    var lanes = assignLanes(meetings);
    var gridStart = GRID_DEFAULT_START;
    var gridEnd = GRID_DEFAULT_END;
    meetings.forEach(function (m) {
      gridStart = Math.min(gridStart, Math.floor(m.start / 60) * 60);
      gridEnd = Math.max(gridEnd, Math.ceil(m.end / 60) * 60);
    });
    if (gridEnd <= gridStart) gridEnd = gridStart + 60;
    var slots = Math.ceil((gridEnd - gridStart) / SLOT_MINUTES);

    // שורה 1 — כותרות
    root.appendChild(el("div", { class: "hd", text: "שעה" }));
    DAYS.forEach(function (d) {
      root.appendChild(
        el("div", { class: "hd" }, [
          el("span", { text: "יום " + dayLetter(d) + "׳" }),
          el("span", { class: "dayname", text: dayName(d) }),
        ])
      );
    });

    // עמודת השעות + משבצות הרקע
    for (var i = 0; i < slots; i++) {
      var minute = gridStart + i * SLOT_MINUTES;
      var onHour = minute % 60 === 0;
      root.appendChild(
        el("div", {
          class: "tl" + (onHour ? " hour" : ""),
          style: { "grid-row": String(i + 2), "grid-column": "1" },
          text: onHour ? fmtTime(minute) : "",
        })
      );
      for (var d = 0; d < DAYS.length; d++) {
        root.appendChild(
          el("div", {
            class: "slot" + (onHour ? " hour" : ""),
            style: {
              "grid-row": String(i + 2),
              "grid-column": String(DAYS[d] + 1),
            },
          })
        );
      }
    }

    // המפגשים עצמם — אחרי המשבצות, כדי שיצוירו מעליהן
    meetings.forEach(function (m) {
      var startSlot = Math.floor((m.start - gridStart) / SLOT_MINUTES);
      var endSlot = Math.ceil((m.end - gridStart) / SLOT_MINUTES);
      if (endSlot <= startSlot) endSlot = startSlot + 1;
      var key = meetingKey(m);
      var clash = soft && soft.marks ? txt(soft.marks[key]) : "";
      var summary = [
        m.name,
        "קבוצה " + m.group_id,
        m.kind,
        m.lecturer,
        fmtTime(m.start) + "–" + fmtTime(m.end),
        m.room,
        clash ? "חפיפה מכוונת עם " + clash : "",
      ]
        .filter(Boolean)
        .join(" · ");

      var style = {
        "grid-row": startSlot + 2 + " / " + (endSlot + 2),
        "grid-column": String(m.day + 1),
      };
      var lane = lanes[key];
      if (lane && lane.lanes > 1) {
        // חלוקת רוחב בסגנון מוטבע בלבד — style.css לא משתנה בשלב הזה.
        style["margin-inline-start"] =
          ((lane.lane * 100) / lane.lanes).toFixed(2) + "%";
        style["margin-inline-end"] =
          (((lane.lanes - lane.lane - 1) * 100) / lane.lanes).toFixed(2) + "%";
      }
      if (clash) {
        style.outline = "2px dashed var(--warn-line, currentColor)";
        style["outline-offset"] = "-3px";
      }

      var block = el(
        "div",
        {
          class: "ev c" + colorOf(m.code) + (clash ? " is-soft" : ""),
          style: style,
          attrs: { title: summary },
        },
        [
          el("b", { text: m.name }),
          el("span", { class: "cell-time", text: fmtTime(m.start) + "–" + fmtTime(m.end) }),
          el("span", { text: m.kind + " · קבוצה " + m.group_id }),
        ]
      );
      if (m.lecturer) block.appendChild(el("span", { text: m.lecturer }));
      if (m.room) block.appendChild(el("span", { text: m.room }));
      if (clash) {
        // הסימון חייב להיות קריא גם בלי צבע ובלי הדפסה בצבע.
        block.appendChild(el("span", { text: "חפיפה מכוונת · " + clash }));
      }
      root.appendChild(block);
    });
  }

  /* --- מצב חמשת השלבים ------------------------------------------------ */

  function renderStepStates() {
    var hasCodes = state.codes.length > 0;
    var hasData = runtime.courses.length > 0;
    var list = schedules();
    var s = runtime.solve;

    var steps = [
      {
        key: "year",
        // בחירת שנה+סמסטר היא שלב שלם גם כשאין לה סמסטר בתוכנית
        // (תוכנית קצרה מ-8 סמסטרים, קיץ, או אין תוכנית כלל).
        locked: false,
        complete: !!txt(state.term),
        text: txt(state.term)
          ? (YEAR_LABELS[state.studyYear] || "") +
            " · סמסטר " +
            txt(state.term) +
            (curriculumSemesterKnown()
              ? " · סמסטר " + txt(state.semester) + " בתוכנית"
              : "")
          : "יש לבחור שנה וסמסטר",
      },
      {
        key: "courses",
        locked: false,
        complete: hasCodes,
        text: hasCodes
          ? state.codes.length +
            " קורסים · " +
            totalCreditsText({ unit: true, short: true })
          : catalogFallbackActive()
          ? "יש לבחור קורסים מהקטלוג"
          : "יש לסמן קורסים",
      },
      {
        key: "days",
        locked: !hasCodes,
        complete: hasCodes && !!s,
        text: !hasCodes
          ? "ממתין לבחירת קורסים"
          : "יעד " +
            state.targetDays +
            " ימים" +
            (s && num(s.min_days, null) !== null
              ? " · מינימום אפשרי " + s.min_days
              : ""),
      },
      {
        key: "lecturers",
        locked: !hasData,
        complete: hasData && (rankedCount() > 0 || pinCount() > 0 || list.length > 0),
        text: !hasData
          ? "ממתין לנתוני הקבוצות"
          : (rankedCount() ? rankedCount() + " מרצים מדורגים" : "בלי העדפת מרצים") +
            (pinCount() ? " · " + pinCount() + " קבוצות נעוצות" : ""),
      },
      {
        key: "schedule",
        locked: !hasCodes,
        complete: list.length > 0,
        text: !hasCodes
          ? "ממתין לבחירת קורסים"
          : list.length
          ? "מוצגת מערכת " +
            (clamp(state.activeSchedule, 0, list.length - 1) + 1) +
            " מתוך " +
            list.length
          : runtime.solveBusy
          ? "מחשב…"
          : "אין מערכת אפשרית עם הבחירות הנוכחיות",
      },
    ];

    var activeAssigned = false;
    steps.forEach(function (step) {
      var node = ui.steps[step.key];
      setText(ui.stepStates[step.key], step.text);
      if (!node) return;
      var isActive = false;
      if (!activeAssigned && !step.locked && !step.complete) {
        isActive = true;
        activeAssigned = true;
      }
      setClass(node, "is-locked", step.locked);
      setClass(node, "is-complete", step.complete && !step.locked);
      setClass(node, "is-active", isActive);
      if (step.locked) node.setAttribute("aria-disabled", "true");
      else node.removeAttribute("aria-disabled");
    });
    if (!activeAssigned) {
      var last = ui.steps.schedule;
      if (last) setClass(last, "is-active", true);
    }
  }

  /* =====================================================================
   * 11. הפעלה
   * ===================================================================== */

  function boot() {
    runtime.restored = loadState();
    // לאיזה סמסטר הבחירה השמורה שייכת. האימוץ החד-פעמי ב-
    // ``applyRecommendedDefaults`` נשען על זה: בחירה ששייכת לסמסטר 5 אינה
    // תשובה לשאלה "מה מומלץ בסמסטר 3", ואימוץ שלה שם היה רושם את כל ההמלצה
    // החדשה כ"בוטלה" ומשאיר את הרשימה ריקה.
    runtime.adoptSemester = runtime.restored ? txt(state.semester) : "";
    cacheElements();
    wireEvents();
    refreshColorMap();
    render();
    fetchBootstrap();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  // ידית קטנה לניפוי מהקונסולה — לא נדרשת לתפעול.
  window.scheduleBuilder = {
    getState: function () {
      return deepCopy(state);
    },
    getRuntime: function () {
      return runtime;
    },
    solveNow: function () {
      return doSolve();
    },
    reset: function () {
      clearSavedState();
      window.location.reload();
    },
  };
})();
