/* =========================================================================
 * app.js — שכבת השאלות והתשובות של SlotWise, בדפדפן.
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
   * 0. נוסח
   * =====================================================================
   * כל הטקסט שהמשתמש/ת רואים מגיע מ-``src/strings.json``. השרת מזרים אותו
   * לעמוד כ-``window.STRINGS`` (ראו ‏index.html), ומכאן קוראים אותו בשתי
   * פונקציות שמחקות בכוונה את ``strings.py`` שבצד השרת — אותו נתיב מנוקד
   * ואותה הצבת ‎{שם}‎, כדי שאותו מפתח ייקרא אותו דבר בשני הצדדים.
   * ===================================================================== */

  var STRINGS = window.STRINGS || {};

  /**
   * ‏?debug=1 מחזיר למסך את מה שנועד למפתח/ת: ספירות, זמני חישוב
   * וספירת הקטלוג. בלעדיו הם יושבים מקופלים תחת "פרטים טכניים".
   */
  var DEBUG = /[?&]debug=1(&|$)/.test(window.location.search);

  /**
   * מפתחות נוסח שלא נמצאו. נאסף כדי שבדיקה בדפדפן תוכל לשאול את העמוד
   * "מה חסר לך", במקום לנחש מהמראה.
   */
  var MISSING_STRINGS = [];

  /**
   * ‏מקור הנוסח לא הגיע בכלל — כלומר ``window.STRINGS`` ריק. זו לא תקלה
   * של מפתח בודד אלא של כל העמוד, והיא מקבלת הודעה משלה כי היא זו
   * שקורית בפועל כששרת ישן עדיין רץ או שהדפדפן מגיש index.html מהמטמון.
   */
  var STRINGS_EMPTY =
    !STRINGS || typeof STRINGS !== "object" || !Object.keys(STRINGS).length;
  if (STRINGS_EMPTY && window.console) {
    window.console.error(
      "[SlotWise] window.STRINGS ריק — אף טקסט בממשק לא ייטען. " +
        "בדרך כלל זה שרת שעלה לפני שהנוסח נוסף (strings.py מחזיק מטמון " +
        "לכל חיי התהליך) או index.html מהמטמון של הדפדפן. " +
        "יש להפעיל מחדש את השרת ולטעון מחדש בלי מטמון."
    );
  }

  /**
   * רושם מפתח חסר: פעם אחת ליומן, ולתוך ``MISSING_STRINGS``.
   *
   * למה בקול רם: עד כאן מפתח חסר יצא כמחרוזת ריקה בחלק מהקריאות וכשם
   * המפתח באחרות, ושתי הצורות נראות על המסך כמו עיצוב — תווית ריקה או
   * המילה "compactness". דף שלם יכול היה להישלח ככה בלי שאיש ישים לב.
   */
  function missingString(path) {
    if (MISSING_STRINGS.indexOf(path) === -1) {
      MISSING_STRINGS.push(path);
      if (window.console) {
        window.console.error("[SlotWise] מפתח נוסח חסר: " + path);
      }
    }
  }

  /**
   * שליפה לפי נתיב מנוקד: ``T("app.header.refresh")``.
   *
   * מפתח חסר **אינו** מוחזר בשקט. הוא נרשם ליומן, נצבר ל-MISSING_STRINGS,
   * ומוחזר מסומן — ``⟦app.header.refresh⟧`` — כדי שייראה על המסך כתקלה
   * ולא כטקסט. ``fallback`` מפורש עדיין מכובד, לשימושים שבהם היעדר ערך
   * הוא מצב לגיטימי.
   */
  function T(path, fallback) {
    var node = STRINGS;
    var parts = String(path).split(".");
    for (var i = 0; i < parts.length; i++) {
      if (!node || typeof node !== "object" || !(parts[i] in node)) {
        node = undefined;
        break;
      }
      node = node[parts[i]];
    }
    if (node === undefined || node === null) {
      if (fallback !== undefined) return fallback;
      missingString(path);
      // \u05D1\u05E4\u05D9\u05EA\u05D5\u05D7 \u05D4\u05EA\u05E7\u05DC\u05D4 \u05D6\u05D5\u05E2\u05E7\u05EA; \u05D1\u05DE\u05E6\u05D1 \u05E8\u05D2\u05D9\u05DC \u05D4\u05D9\u05D0 \u05E0\u05E9\u05D0\u05E8\u05EA \u05D1\u05D9\u05D5\u05DE\u05DF \u05D1\u05DC\u05D1\u05D3. \u05E1\u05D8\u05D5\u05D3\u05E0\u05D8/\u05D9\u05EA
      // \u05E9\u05D1\u05D0\u05D5 \u05DC\u05D1\u05E0\u05D5\u05EA \u05DE\u05E2\u05E8\u05DB\u05EA \u05D0\u05D9\u05E0\u05DD \u05E6\u05E8\u05D9\u05DB\u05D9\u05DD \u05DC\u05E8\u05D0\u05D5\u05EA \u05E9\u05DD \u05E9\u05DC \u05DE\u05E4\u05EA\u05D7 \u05E4\u05E0\u05D9\u05DE\u05D9 \u2014 \u05D6\u05D4 \u05DE\u05D1\u05D4\u05D9\u05DC,
      // \u05D5\u05D0\u05D9\u05DF \u05DC\u05D4\u05DD \u05DE\u05D4 \u05DC\u05E2\u05E9\u05D5\u05EA \u05E2\u05DD \u05D4\u05DE\u05D9\u05D3\u05E2.
      return DEBUG ? "\u27E6" + path + "\u27E7" : "";
    }
    return node;
  }

  /**
   * שליפה + הצבת פרמטרים: ``Tf("app.scrape.refreshing", { count: 6 })``.
   * המשפט נשמר שלם ב-JSON ולא מפוצל לשברים, כדי שמי שעורך נוסח יראה
   * משפט ולא פאזל.
   */
  function Tf(path, params) {
    var text = T(path);
    if (typeof text !== "string") return text;
    if (!params) return text;
    Object.keys(params).forEach(function (key) {
      text = text.split("{" + key + "}").join(String(params[key]));
    });
    return text;
  }

  /* =====================================================================
   * 1. קבועים
   * ===================================================================== */

  /**
   * שם ישן, בכוונה. השם הזה **לא** משתנה עם שינוי שם המוצר ל-SlotWise,
   * משתי סיבות שכל אחת מהן מספיקה:
   *   1. ‏tests/test_recommended_defaults_browser.py קורא בדיוק את המפתח הזה.
   *   2. מפתח חדש פירושו מצב שמור שלא נמצא — כלומר מחיקה שקטה של הקורסים
   *      שנבחרו, הנעיצות, דירוג המרצים וחובות הנוכחות של מי שכבר משתמש/ת.
   * שינוי שלו מחייב מסלול הגירה שקורא את הישן וכותב לחדש, ולא החלפת מחרוזת.
   */
  var STORAGE_KEY = "braude_schedule_builder_v1";

  //: אחרי כמה ימים קטלוג נחשב ישן מספיק כדי לומר עליו משהו.
  //:
  //: לא 24 שעות כמו הסף של המסד הפרטי. קטלוג שנשלח עם התוכנה הוא **אותו
  //: קטלוג** לכל המשתמשים, והוא מתיישן לאט: לוח השעות של סמסטר משתנה
  //: בשוליים אחרי פרסומו. ‏45 יום הם בערך אמצע סמסטר — מספיק זמן כדי
  //: שכדאי לבדוק, ולא כל כך קצר שההודעה תהפוך לרעש קבוע.
  var CATALOG_STALE_DAYS = 45;
  var STORAGE_SCHEMA = 1;

  /**
   * ערכת הצבעים. מפתח נפרד מ-``STORAGE_KEY`` בכוונה: זו העדפת תצוגה ולא
   * חלק מהבחירה הסמסטריאלית, ואיפוס של האחת לא אמור לגרור את השנייה.
   * ‏static/theme.js קורא את אותו מפתח לפני הציור הראשון — שינוי כאן מחייב
   * שינוי גם שם.
   */
  var THEME_KEY = "slotwise_theme";
  var THEME_CHOICES = ["system", "light", "dark"];

  var SOLVE_DEBOUNCE_MS = 150;
  var SEARCH_DEBOUNCE_MS = 250;
  /** כמה שורות קטלוג להביא בכל עיון. מספיק כדי לגלול, מעט מספיק כדי לטעון מיד. */
  var BROWSE_LIMIT = 60;
  var TOAST_MS = 5000;

  /** רזולוציית הרשת השבועית: שורה לכל רבע שעה (כמו בחוזה שב-index.html). */
  var SLOT_MINUTES = 15;
  var GRID_DEFAULT_START = 8 * 60; // 08:00
  var GRID_DEFAULT_END = 20 * 60; // 20:00

  var DAY_LETTERS = T("app.terms.dayLetters", {});
  var DAY_NAMES = T("app.terms.dayNames", {});
  var DAYS = [1, 2, 3, 4, 5, 6];

  /**
   * סדר תצוגה של סוגי רכיב — זהה ל-models.KIND_ORDER.
   *
   * המחרוזות האלה **אינן** עוברות ל-strings.json למרות שהן מוצגות על המסך:
   * הן מגיעות מהשרת בשדה ``kind`` ומשמשות כאן להשוואה, למיון ולמפתח
   * במפות הנוכחות והנעיצות. עריכת נוסח בקובץ הנוסח הייתה מנתקת בשקט את
   * ההתאמה לנתונים. אותו נימוק תקף לקודי הסמסטר ("א"/"ב"/"קיץ") שלמטה.
   */
  var KIND_ORDER = ["הרצאה", "תרגול", "מעבדה", "פרויקט", 'שו"ת', "אחר"];

  var TERMS_FALLBACK = [
    { value: "א", label: T("app.terms.fallbackTerms.winter", "") },
    { value: "ב", label: T("app.terms.fallbackTerms.spring", "") },
    { value: "קיץ", label: T("app.terms.fallbackTerms.summer", "") },
  ];

  var YEAR_LABELS = T("app.terms.yearLabels", {});

  /**
   * אילו שלבים אפשר לקפל ביד. שלב 5 (המערכת) אינו ברשימה בכוונה: הוא הפלט,
   * והוא גם היחיד שנשלח למדפסת — שלב מקופל היה מדפיס דף ריק.
   */
  var COLLAPSIBLE_STEPS = ["year", "courses", "days", "lecturers"];

  /**
   * ומה מתקפל **מעצמו** כשחוזרים לעמוד. שלב 1 אינו ברשימה: הוא נקודת
   * הכניסה — שנה, סמסטר ומסלול הם מה שמחליפים הכי הרבה — והוא גם קצר
   * ממילא. אפשר לקפל אותו ביד, פשוט לא אוטומטית.
   */
  var AUTO_COLLAPSE_STEPS = ["courses", "days", "lecturers"];

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

  /**
   * שמות עבריים לרכיבי הניקוד. ‏scheduler.py מייצר חמישה קבועים
   * (‏lecturer, days, gaps, compactness, late_finish) ורכיב שישי מותנה
   * (‏soft_conflict, רק כשיש חפיפה מכוונת בפועל). כל מפתח חייב להופיע כאן —
   * מפתח חסר היה דולף למסך בשמו הפנימי, וכך בדיוק "late_finish" הופיע
   * לסטודנט/ית כתווית.
   */
  var BREAKDOWN_HE = T("app.score.breakdown", {});

  /**
   * רכיבי ניקוד שכבר מוצגים כמדידה משלהם בשורת המדדים.
   * ‏"חורים 3:00" (זמן בפועל) ו-"חורים ‎-12" (תרומה לניקוד) הם שני דברים
   * שונים בתכלית שנשאו אותה תווית בדיוק, זה לצד זה. המדידה נשארת על המסך,
   * והתרומה לניקוד עוברת לתיאור של "ניקוד" — שם היא מובנת בהקשר.
   */
  var BREAKDOWN_HAS_OWN_FACT = {
    lecturer: true,
    days: true,
    gaps: true,
  };

  var PHASE_HE = T("app.phases.names", {});

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

  /**
   * משך כטקסט אחד לכל המסך: ‏"3:00 שעות".
   *
   * ‏fmtSpan מחזיר "3:00" בלבד, וזה מספר בלי יחידה — ליד "19:50" של שעת
   * הסיום אי אפשר לדעת מי מהם משך ומי שעה ביום. היחידה נוספת כאן, פעם
   * אחת, וכל מקום שמציג משך עובר דרך הפונקציה הזאת.
   */
  function fmtDuration(minutes) {
    return Tf("app.schedule.duration", { span: fmtSpan(minutes) });
  }

  /**
   * ‏87 -> "87%". הניסוח היחיד של ההתאמה, בכל מקום שבו היא מוצגת.
   *
   * ‏עד 2026-09-08 הנוסח היה ‎"{score} / 100"‎, והוא נשבר בדו-כיווניות:
   * ‏"87 / 100" הוא שני מקטעי מספר עם מפריד נייטרלי ביניהם, ובפסקה RTL
   * הנייטרלי מקבל כיוון ימין-לשמאל והמקטעים מסודרים מימין לשמאל — כלומר
   * התא הראה ‎"100 / 87"‎. בפאנל הניקוד זה הוסתר על ידי ‎class="ltr"‎;
   * בטבלת ההשוואה, שבנתה את אותה מחרוזת לתוך ‎<td>‎ רגיל, זה נראה.
   *
   * ‏אחוז אחד אומר בדיוק את מה ש-‎"87 / 100"‎ אמר, בפחות מקום, ואי אפשר
   * לסדר אותו מחדש: ‎%‎ הוא ET, וכלל W5 של אלגוריתם הדו-כיווניות מצרף
   * ‏ET צמוד ל-EN לאותו מקטע. מספר אחד אינו יכול להתהפך — התיקון מסלק
   * את הסיבה, ולא את הסימפטום.
   */
  function fmtFit(score) {
    return Tf("app.schedule.fitValue", { score: clamp(Math.round(num(score, 0)), 0, 100) });
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
    if (secs < 60) return T("app.age.lessThanMinute", "");
    var mins = Math.floor(secs / 60);
    if (mins < 60)
      return mins === 1
        ? T("app.age.oneMinute", "")
        : Tf("app.age.minutes", { count: mins });
    var hours = Math.floor(mins / 60);
    if (hours < 24)
      return hours === 1
        ? T("app.age.oneHour", "")
        : Tf("app.age.hours", { count: hours });
    var days = Math.floor(hours / 24);
    if (days === 1) return T("app.age.oneDay", "");
    if (days < 30) return Tf("app.age.days", { count: days });
    var months = Math.floor(days / 30);
    return months === 1
      ? T("app.age.oneMonth", "")
      : Tf("app.age.months", { count: months });
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

  /** תווית הצפה. ריק = **מסירים** את המאפיין, ולא ``title=""``: תווית
   *  ריקה עדיין נחשבת תווית, וחלק מהקוראים הקוליים מכריזים עליה. */
  function setTitle(node, value) {
    if (!node) return;
    var text = txt(value);
    if (text) node.setAttribute("title", text);
    else node.removeAttribute("title");
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

  /** ‏"קורס אחד" / "3 קורסים" — ניטרלי מגדרית, כמו שאר הטקסטים. */
  function coursesHe(n) {
    var count = Math.max(0, Math.round(num(n, 0)));
    return count === 1
      ? T("app.age.oneCourse", "")
      : Tf("app.age.manyCourses", { count: count });
  }

  /** ‏"קורס אחד ... אינו מעודכן" מול "3 קורסים ... אינם מעודכנים". */
  function notUpdatedHe(n, middle) {
    var count = Math.max(0, Math.round(num(n, 0)));
    return Tf(count === 1 ? "app.age.notUpdatedOne" : "app.age.notUpdatedMany", {
      courses: coursesHe(count),
      middle: txt(middle),
    });
  }

  /* =====================================================================
   * 3. מצב + שמירה מקומית
   * ===================================================================== */

  function defaultState() {
    return {
      schema: STORAGE_SCHEMA,
      // ‏זהות, לא העדפה: מי הסטודנט/ית. אין לזה ברירת מחדל סבירה, כי
      // ‏האפליקציה אינה יודעת. ‏null / "" פירושם "עוד לא נבחר", וכל השלבים
      // שאחריהם נעולים עד שיש שלושתם — ראו identityChosen().
      studyYear: null, // שנה בתוכנית (1..4), או null כשעוד לא נבחרה
      term: "", // סמסטר בידיעון: א / ב / קיץ, או "" כשעוד לא נבחר
      semester: "5", // סמסטר בתוכנית הלימודים (1..8), "" אם אין
      academicYear: "", // שנה"ל (למשל תשפ"ז) — מגיע מהשרת
      codes: [], // קודי הקורסים שנבחרו, לפי סדר הוספה
      // מקור הבחירה. ‏codes נשאר מקור האמת היחיד לציור; שלושת אלה רק זוכרים
      // *מי* סימן כל קורס, כדי שהחלפת שנה/סמסטר תחליף את ההמלצה בלי לגעת
      // במה שנבחר ידנית, וכדי שביטול ידני של קורס מומלץ לא יבוטל על ידי
      // משיכה מאוחרת של אותה רשימה.
      autoSemester: "", // הסמסטר שההמלצה שלו מוחלת כרגע. "" = אין המלצה מוחלת
      // והמסלול שלו. מספר הסמסטר לבדו אינו מזהה המלצה: החלפת מסלול אינה
      // משנה אותו, וסטודנט/ית שעברו מהנדסת תוכנה לאזרחית נשארו עם רשימת
      // התוכנה מסומנת מתחת לקורסי האזרחית.
      autoProgram: "",
      // ‏ומועד הכניסה שלו. אותו מספר סמסטר מציין קורסים אחרים בכל מועד,
      // ולכן מסלול+סמסטר לבדם אינם מזהים המלצה במסלול עם מועדי כניסה.
      autoIntake: "",
      // ‏וההתמחות+המסלול שלו: בחירה אחרת מחליפה את רשימת ההמלצה.
      autoTrack: "",
      autoCodes: [], // מה שסומן אוטומטית עבור autoSemester
      manualCodes: [], // מה שנוסף ידנית (חיפוש/קטלוג/בחירה) — שורד החלפת סמסטר
      autoDropped: [], // קורסים מומלצים שבוטלו ידנית — לא לסמן שוב
      // האם כבר קבענו מקור לכל קוד שנבחר. ‏autoSemester ריק אינו סימן טוב
      // מספיק לשאלה הזאת: הוא ריק גם לפני ההחלה הראשונה וגם אחרי מעבר
      // לקיץ, ובלי הבחנה ביניהם חזרה מקיץ הייתה מסמנת את כל ההמלצה
      // כ"בוטלה" ומשאירה את הרשימה ריקה.
      provenanceReady: false,
      known: {}, // מטמון שמות/נ"ז: {code: {name, credits, semester}}
      // ‏null = עוד לא נבחר יעד. הפותר מקבל 6, שהוא קנס אפס — "בלי
      // העדפה" הוא מצב אמיתי, לא ניחוש של 4 שמעניש מערכות בנות 5 ימים.
      targetDays: null,
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
      // מועד הכניסה, למסלול שהשנתון מדפיס לו תוכנית לכל מועד. ריק לכל
      // מסלול אחר, ושם גם התיבה עצמה מוסתרת. ‏**זה חלק מהזהות**: מספר
      // הסמסטר מציין דבר אחר בכל מועד, ולכן בלי בחירה כאן אין למסלול
      // תוכנית ולא לוח סמסטרים.
      intake: "",
      // ‏ההתמחות, מסלול ההתמחות (סוג תכן הנדסי / התנסות מעשית) וההתמחות
      // המשנית — רק למסלול שיש לו אותם, ורק מהסמסטר שהתוכנית בוחרת בו
      // (``specialization`` ברשימת ``programs``). ריק = לא נבחר.
      specialization: "",
      route: "",
      secondarySpecialization: "",
      earliest: null, // דקות מחצות, או null
      latest: null,
      blocked: [], // [[יום, התחלה, סוף], ...]
      pinned: {}, // {code: {kind: group_id}}
      ranked: {}, // {code: [שם מרצה, ...]}
      topN: 5,
      activeSchedule: 0,
      // קיפול שלבים: {מפתח שלב: true/false}. **רק בחירה מפורשת** נרשמת כאן,
      // ולכן מפתח חסר פירושו "לא הוכרע" — וזה מה שמתיר לקיפול האוטומטי
      // לפעול פעם אחת בלי לדרוס העדפה שנקבעה ביד.
      collapsed: {},
    };
  }

  var state = defaultState();

  /** מה שלא נשמר בין רענונים: תשובות שרת, סטטוס, שגיאות. */
  var runtime = {
    // שלב 4: הקורס הפתוח באקורדיון (null = ברירת מחדל, "" = הכול סגור),
    // אילו ⓘ פתוחים, האם גלולת "ללא חובת נוכחות" פתוחה, והדירוג האחרון.
    openCourse: null,
    attInfoOpen: {},
    attOffOpen: false,
    popRank: null,
    restored: false,
    ready: false,
    bootstrap: null,
    bootstrapError: null,
    semesterCourses: [],
    // ‏למי שייכת הרשימה: סמסטר|מסלול|מועד|התמחות — כדי לא לספור בשבב של
    // ‏שלב 1 רשימה של בחירה קודמת בזמן שהחדשה עוד בדרך.
    semesterCoursesFor: "",
    // ‏``semester_notes`` מהשרת: {placed: [...], anywhere: [...]}.
    semesterNotes: null,
    semesterError: null,
    catalogQuery: "",
    catalogResults: [],
    catalogError: null,
    catalogBusy: false,
    // ‏features.fetch_on_demand מ-/api/bootstrap: האם לשרת הזה מותר בכלל
    // לפנות לידיעון. ‏false הוא המצב המאורח — שם כל הנתונים באים מהקטלוג
    // שנבנה בלילה, ולכן "ניסיון חוזר מהידיעון" הוא כפתור שאין מאחוריו
    // רשת. ברירת המחדל ``true`` שומרת על ההתנהגות המקומית עד שהשרת עונה.
    canFetch: true,
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
    // ‏false = הנ"ז שחולצה מהשנתון אינה שווה לסה"כ שהשנתון מדפיס.
    // ‏null = אין בדיקה כזאת לתוכנית הזאת.
    semesterReconciles: null,
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
    solveAbort: null,       // ‏AbortController של החישוב הרץ
    solveCancelled: false,  // בוטל ביודעין — לא תקלה
    // גיל הקטלוג מ-/api/catalog/meta. ‏null = עוד לא נטען, או שאין קטלוג.
    catalogMeta: null,
    // ההיפוך של הוויתור האחרון — ממוקד, לא צילום מצב. ראי undoRelaxation.
    lastRelax: null,
    colors: Object.create(null),
    dismissed: Object.create(null),
    // ‏האם המשתמש/ת כבר נגעו במשהו בעמוד. הקיפול האוטומטי פועל רק לפני
    // הנגיעה הראשונה: שלב שנסגר מתחת לאצבע באמצע עבודה הוא הפרעה, לא עזרה.
    userActed: false,
    // האם גללנו מעבר לשלב 1 — התנאי להופעת הסרגל המצוף.
    pastFirstStep: false,
    // שכבת המערכת: פתוחה, ולאן להחזיר את הפוקוס בסגירה.
    overlayOpen: false,
    overlayReturnTo: null,
    detailReturnTo: null,
    // אילו שלבים כבר נשקלו לקיפול אוטומטי — שיקול אחד לכל שלב, לכל טעינה.
    autoCollapsed: Object.create(null),
    // איזה ‏<details> בתוך באנר פתוח כרגע, לפי מפתח הבאנר.
    // ‏renderBanners בונה את #banners מחדש בכל ציור — וגם כל שתי שניות בזמן
    // רענון — ולכן מצב "פתוח" של אלמנט חייב לחיות כאן ולא ב-DOM, אחרת הרשימה
    // נסגרת מתחת לאצבע בכל סיבוב.
    bannerOpen: Object.create(null),
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
    base.autoProgram = txt(base.autoProgram);
    base.autoIntake = txt(base.autoIntake);
    base.autoTrack = txt(base.autoTrack);
    base.specialization = txt(base.specialization);
    base.route = txt(base.route);
    base.secondarySpecialization = txt(base.secondarySpecialization);
    ["autoCodes", "manualCodes", "autoDropped"].forEach(function (k) {
      if (!Array.isArray(base[k])) base[k] = [];
      base[k] = uniq(base[k].map(txt).filter(Boolean));
    });
    // מצב שנשמר לפני שהשדות האלה היו קיימים מגיע בלי הדגל, ולכן בלי מקור
    // ידוע לקודים שבו — בדיוק המקרה שהאימוץ ב-applyRecommendedDefaults נועד לו.
    base.provenanceReady = base.provenanceReady === true;
    // ‏הגירה ממצב שנשמר כשהסימון היה אוטומטי. שם ``codes`` הוא מה שהיה
    // מסומן ו-``manualCodes`` ריק, כי ההבחנה אז הייתה בין "המערכת סימנה"
    // ל"היא הוסיפה". מרגע שאין סימון אוטומטי כל מה שמסומן הוא שלה, ובלי
    // השורה הזאת ``applyRecommendedDefaults`` היה כותב ``codes: manual``
    // ומוחק לסטודנט/ית קיימת את כל הבחירה בטעינה הראשונה אחרי השדרוג.
    if (base.codes.length && !base.manualCodes.length) {
      base.manualCodes = base.codes.slice();
    }
    if (!base.known || typeof base.known !== "object") base.known = {};
    if (!base.pinned || typeof base.pinned !== "object") base.pinned = {};
    if (!base.ranked || typeof base.ranked !== "object") base.ranked = {};
    if (!base.attendance || typeof base.attendance !== "object") base.attendance = {};
    if (!base.collapsed || typeof base.collapsed !== "object") base.collapsed = {};
    base.allowSoftConflicts = true;  // גם מצב ישן שנשמר ב-localStorage מיושר
    if (!Array.isArray(base.blocked)) base.blocked = [];
    base.targetDays =
      base.targetDays === null || base.targetDays === undefined
        ? null
        : clamp(Math.round(num(base.targetDays, 4)), 2, 6);
    base.topN = clamp(Math.round(num(base.topN, 5)), 1, 20);
    // ‏null שורד: הוא "עוד לא נבחרה שנה", ולא ערך פגום. ‏clamp אל 3 היה
    // ממציא זהות למי שלא בחר/ה — בדיוק מה שהמסך הזה בא להפסיק.
    base.studyYear =
      base.studyYear === null || base.studyYear === undefined || base.studyYear === ""
        ? null
        : clamp(Math.round(num(base.studyYear, 3)), 1, 4);
    base.term = txt(base.term);
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
            Tf("app.errors.badResponse", { status: res.status });
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

  function postJSON(path, body, signal) {
    return request(path, {
      method: "POST",
      body: JSON.stringify(body || {}),
      signal: signal,
    });
  }

  /**
   * שגיאה בשפה של מי שקורא אותה: מה קרה, ומה אפשר לעשות עכשיו.
   *
   * ‏"טעינת נתוני הקורסים נכשלה: TypeError: Failed to fetch" אומר למי
   * שכתב את הקוד מה קרה, ולסטודנט/ית לא אומר דבר — ובעיקר לא אומר
   * שהבחירות שלהם לא אבדו, שזו השאלה הראשונה שעולה.
   */
  function errorText(err) {
    if (!err) return T("app.errors.unknown", "");
    if (err.name === "AbortError") return T("app.schedule.solvingCancelled");
    var status = num(err.status, 0);
    // ‏fetch נכשל בלי סטטוס = לא הגענו לשרת בכלל.
    if (!status) return T("app.errors.network");
    if (status >= 500) return Tf("app.errors.serverFault", { status: status });
    if (status >= 400) {
      return Tf("app.errors.badRequest", {
        error: txt(err.message) || T("app.errors.unknown", ""),
      });
    }
    return txt(err.message) || T("app.errors.unknown", "");
  }

  /** מספרים רצים — תשובה שמגיעה אחרי בקשה חדשה יותר נזרקת. */
  var seq = { semester: 0, courses: 0, solve: 0, catalog: 0, browse: 0, electives: 0 };

  /* =====================================================================
   * 5. נגזרות מהמצב
   * ===================================================================== */

  /** הרשומה של המסלול שנבחר ברשימת ``programs`` של ‏/api/bootstrap. */
  function programEntry() {
    var chosen = txt(state.program);
    var list = runtime.programs || [];
    for (var i = 0; i < list.length; i++) {
      if (txt(list[i].id) === chosen) return list[i];
    }
    return null;
  }

  /**
   * מועדי הכניסה של המסלול שנבחר, או רשימה ריקה. ריק = מסלול רגיל,
   * והתיבה כולה מוסתרת.
   */
  function programIntakes() {
    var entry = programEntry();
    var list = entry && entry.intakes;
    return Array.isArray(list) ? list : [];
  }

  /**
   * המסלול דורש מועד כניסה, ועוד לא נבחר אחד. זה **אינו** "אין תוכנית":
   * יש שתיים, והשאלה פתוחה — ולכן הנוסח מבקש לבחור ולא מציע את הקטלוג.
   */
  function intakeMissing() {
    return programIntakes().length > 0 && !txt(state.intake);
  }

  /**
   * ‏המסלול נשאל על מספר סמסטר במקום על שנה+סמסטר.
   *
   * ‏לתוכנית שנבחרת לפי מועד כניסה אין לוח של שנה×סמסטר: מי שמתקבל/ת
   * באביב מתחיל/ה בסמסטר ב', כך שהמשבצת "שנה א' · סמסטר א'" ריקה, ומספר
   * השנה עצמו היה ניחוש. מה שידוע הוא מספר הסמסטר בתוכנית — ולכן הוא
   * הדבר היחיד שנשאל, והסמסטר הקלנדרי נגזר ממנו.
   */
  function usesPlanSemester() {
    return programIntakes().length > 0;
  }

  /**
   * ‏הסמסטר הקלנדרי (א/ב) שמספר הסמסטר נופל בו, **מתוך התוכנית עצמה**.
   *
   * ‏הכלל הוא "מועד חורף: אי-זוגי=א, זוגי=ב; מועד אביב: הפוך", והוא כבר
   * מיושם בקובץ התוכנית של כל מועד. קריאה ממנו ולא חישוב מחדש כאן היא מה
   * ששומר על מקור אמת אחד: קובץ שיתוקן פעם אחת מתקן גם את הממשק, ואין
   * עותק שני של הכלל שיכול להיפרד ממנו בשקט.
   *
   * ‏זה **הסמסטר שנשלח לשרת** בכל /api/courses ו-/api/solve, ולכן טעות
   * כאן אינה תצוגתית: היא בונה מערכת מקבוצות של הסמסטר הלא נכון.
   */
  function planTermFor(semester) {
    var rec = semesterInfo(semester);
    return rec ? txt(rec.term) : "";
  }

  /** התווית של המועד שנבחר ("חורף"), או ה-id שלו אם אין תווית. */
  function intakeLabel() {
    var list = programIntakes();
    for (var i = 0; i < list.length; i++) {
      if (txt(list[i].id) === txt(state.intake)) {
        return txt(list[i].label) || txt(list[i].id);
      }
    }
    return txt(state.intake);
  }

  /** ‏"סמסטר 4 · סמסטר א׳ (חורף)" — מה שהשרת גזר לסמסטר שנבחר. */
  function planSemesterLabel() {
    var rec = semesterInfo(state.semester);
    return (
      (rec && txt(rec.label)) ||
      Tf("app.year.summaryPlanNoCount", { n: txt(state.semester) })
    );
  }

  /**
   * לוח הסמסטרים של המסלול שנבחר. ‏semesterOf() ממפה שנה+סמסטר למספר
   * סמסטר לפני כל משיכה מהשרת, ולכן הוא חייב את הלוח הנכון כבר כאן:
   * מתמטיקה שימושית היא תוכנית תלת-שנתית בת שישה סמסטרים, ולוח של שמונה
   * היה מציע לה סמסטר 7 שאינו קיים — ומאז שיש לה תוכנית לכל מועד כניסה,
   * גם *איזה* לוח מבין השניים נקבע כאן.
   * בלי לוח למסלול — הלוח הראשי, כפי שהיה קודם.
   */
  function bootSemesters() {
    if (!runtime.bootstrap) return [];
    // מסלול עם מועדי כניסה: הלוח הוא של המועד שנבחר, ובלי מועד אין לוח
    // כלל. הוא אינו מופיע ב-``semesters_by_program``, ולכן הענף הזה קודם.
    if (programIntakes().length) {
      if (!txt(state.intake)) return [];
      var byIntake = runtime.bootstrap.semesters_by_program_intake || {};
      var forProgram = byIntake[txt(state.program)] || {};
      var rows = forProgram[txt(state.intake)];
      return rows && rows.length
        ? pickList({ semesters: rows }, ["semesters"], "semester")
        : [];
    }
    var byProgram = runtime.bootstrap.semesters_by_program;
    if (byProgram && txt(state.program)) {
      var mine = byProgram[txt(state.program)];
      // מסלול שאין לו תוכנית מקבל רשימה ריקה, ולא את הלוח של מסלול אחר.
      // בלי זה סטודנט/ית לביוטכנולוגיה — שלמחלקה שלהם אין בכלל פרק שנתון —
      // היו רואים "סמסטר 5 בתוכנית הלימודים" שנלקח מהנדסת תוכנה.
      return mine && mine.length
        ? pickList({ semesters: mine }, ["semesters"], "semester")
        : [];
    }
    return pickList(runtime.bootstrap, ["semesters"], "semester");
  }

  /** האם לשרת יש בכלל לוח סמסטרים למסלול שנבחר. */
  function programHasPlan() {
    // עם מועדי כניסה התשובה היא של המועד שנבחר, ו-``bootSemesters`` כבר
    // יודע לבחור אותו. בלי מועד אין לוח, וזה מצב תקין ולא שרת ישן.
    if (programIntakes().length) return bootSemesters().length > 0;
    var byProgram = runtime.bootstrap && runtime.bootstrap.semesters_by_program;
    if (!byProgram || !txt(state.program)) return true; // שרת ישן — לא מכריעים
    var mine = byProgram[txt(state.program)];
    return !!(mine && mine.length);
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
    // אין לוח למסלול הזה ⇒ אין לו סמסטר בתוכנית. הניחוש האריתמטי שלמטה
    // שייך רק לשרת ישן שלא שלח לוח בכלל.
    if (!programHasPlan()) return "";
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

  /**
   * האם המסלול הוא בכלל שאלה. שרת בלי רשימת מסלולים מסתיר את התיבה
   * (‏renderProgramSelect), ואז אין מה לדרוש — דרישה כזאת הייתה נועלת את
   * כל המסך בלי דרך לפתוח אותו.
   */
  function programRequired() {
    return !!(runtime.programs && runtime.programs.length);
  }

  /**
   * ‏האם ידוע מי הסטודנט/ית: מסלול, שנה וסמסטר — שלושתם.
   *
   * ‏זה השער לכל מה שאחריו. רשימת הקורסים המומלצת, ה-‎semester‎ שנשלח
   * לשרת והפתרון עצמו כולם נגזרים מהשלושה האלה, ולכן לפניהם אין מה
   * לשאול ואין מה להציג. השלבים 2..5 נעולים, כל אחד עם שורה שאומרת למה —
   * אותו דפוס שכבר קיים ל"אין עדיין קורסים".
   */
  function identityChosen() {
    if (!(!programRequired() || !!txt(state.program))) return false;
    // מסלול עם מועדי כניסה נשאל שלוש שאלות אחרות: מסלול, מועד, ומספר
    // סמסטר. ‏``studyYear`` נשאר ריק שם לנצח, ודרישה שלו הייתה נועלת את
    // כל המסך על שאלה שלא נשאלה.
    if (usesPlanSemester()) {
      return !!txt(state.intake) && !!txt(state.semester) && !!txt(state.term);
    }
    return num(state.studyYear, null) !== null && !!txt(state.term);
  }

  /* --- התמחות ומסלול (DESIGN.md, "Program, year and semester") ----- */

  /**
   * ‏בלוק ``specialization`` של המסלול, מרשימת ``programs`` של
   * ‏/api/bootstrap. ‏null = למסלול אין התמחויות, ואין מה להציג.
   * ‏``s`` אופציונלי: המטפלים בשינוי שואלים על המצב שהם עומדים לכתוב.
   */
  function programSpec(s) {
    var chosen = txt((s || state).program);
    var list = runtime.programs || [];
    for (var i = 0; i < list.length; i++) {
      if (txt(list[i].id) === chosen) {
        var spec = list[i].specialization;
        return spec && Array.isArray(spec.options) && spec.options.length ? spec : null;
      }
    }
    return null;
  }

  /** מספר הסמסטר בתוכנית, או 0 כשאין (קיץ, מסלול בלי תוכנית). */
  function planNumber(s) {
    return Math.round(num(txt((s || state).semester), 0)) || 0;
  }

  /** תיבת ההתמחות מוצגת: יש התמחויות, ומהסמסטר שבו בוחרים אותן. */
  function specializationShown(s) {
    var spec = programSpec(s);
    var n = planNumber(s);
    return !!spec && n > 0 && n >= num(spec.choose_from_semester, 0);
  }

  /** ההתמחות שנבחרה, רק אם היא תקפה לסמסטר ולמסלול הנוכחיים. */
  function chosenSpecialization(s) {
    var spec = programSpec(s);
    var value = txt((s || state).specialization);
    return specializationShown(s) && spec.options.indexOf(value) !== -1 ? value : "";
  }

  /**
   * ‏קבוצת המסלולים שחלה עכשיו, או null. בחשמל ("סוג תכן הנדסי") היא
   * ‏חלה על כולם מסמסטר 7; בתעשייה וניהול ("התנסות מעשית") רק למי שבחר/ה
   * ‏תכן ותפעול — ולכן היא נשאלת רק אחרי ההתמחות.
   */
  function routeGroup(s) {
    var spec = programSpec(s);
    if (!spec) return null;
    var n = planNumber(s);
    var mine = chosenSpecialization(s);
    var groups = spec.routes || [];
    for (var i = 0; i < groups.length; i++) {
      var g = groups[i];
      var wanted = (g.applies_to && g.applies_to.specialization) || [];
      if (n <= 0 || n < num(g.from_semester, 0)) continue;
      if (wanted.length && wanted.indexOf(mine) === -1) continue;
      return g;
    }
    return null;
  }

  function chosenRoute(s) {
    var g = routeGroup(s);
    var value = txt((s || state).route);
    return g && (g.options || []).indexOf(value) !== -1 ? value : "";
  }

  /** ‏"התמחות משנית" — בחשמל, רק כשסוג התכן הוא מחקרי או פרויקט גמר. */
  function secondaryShown(s) {
    var spec = programSpec(s);
    var sec = spec && spec.secondary;
    if (!sec) return false;
    var n = planNumber(s);
    if (n <= 0 || n < num(sec.from_semester, 0)) return false;
    return (sec.when_route || []).indexOf(chosenRoute(s)) !== -1;
  }

  function secondaryOptions(s) {
    var spec = programSpec(s);
    var primary = chosenSpecialization(s);
    return spec
      ? spec.options.filter(function (o) {
          return o !== primary;
        })
      : [];
  }

  function chosenSecondary(s) {
    var value = txt((s || state).secondarySpecialization);
    return secondaryShown(s) && secondaryOptions(s).indexOf(value) !== -1 ? value : "";
  }

  /** התווית של תיבת המסלול: "סוג תכן הנדסי", "התנסות מעשית". */
  function routeLabel(g) {
    var labels = T("ui.fields.routeLabels", {}) || {};
    return txt(labels[txt(g && g.id)]) || T("ui.fields.route");
  }

  /**
   * ‏מה עוד חסר בבחירה, בשם התיבה ("התמחות", "סוג תכן הנדסי"), או "".
   * ‏כשהתיבה מוצגת היא חובה (DESIGN.md) — השלב אינו מושלם בלעדיה. שאר
   * ‏השלבים נשארים פתוחים, ובלי בחירה רשימת הקורסים היא זו של היום.
   */
  function trackMissing() {
    var g = routeGroup();
    var spec = programSpec();
    if (g && !chosenRoute()) return routeLabel(g);
    if (specializationShown() && !chosenSpecialization()) {
      return spec && spec.secondary ? T("ui.fields.specializationPrimary") : T("ui.fields.specialization");
    }
    if (secondaryShown() && !chosenSecondary()) return T("ui.fields.specializationSecondary");
    return "";
  }

  /** מה שנשלח לשרת ומה שההמלצה שייכת לו: ההתמחות והמסלול התקפים. */
  function trackSig() {
    // ‏"" בלי בחירה, ולא "|": מצב שמור מלפני התיבות נושא ``autoTrack: ""``,
    // ‏וחתימה אחרת הייתה מחליפה לכולם את ההמלצה בטעינה הראשונה.
    var spec = chosenSpecialization();
    var route = chosenRoute();
    return spec || route ? spec + "|" + route : "";
  }

  /**
   * ‏מנקה בחירה שכבר אינה חלה — אחרי החלפת מסלול או סמסטר. סמסטר ריק
   * ‏(קיץ) אינו מנקה: שם פשוט אין תוכנית, וההתמחות לא השתנתה.
   */
  function pruneTrackChoices(s) {
    if (!programSpec(s)) {
      s.specialization = "";
      s.route = "";
      s.secondarySpecialization = "";
      return;
    }
    if (planNumber(s) <= 0) return;
    s.specialization = chosenSpecialization(s);
    s.route = chosenRoute(s);
    s.secondarySpecialization = chosenSecondary(s);
  }

  /**
   * ‏האפשרות הריקה שבראש כל תיבה. ‏disabled ולא רק ריקה: אחרי שבחרו,
   * חזרה אל "בחר/י…" אינה בחירה אלא מחיקה, ואין לה משמעות כאן.
   */
  /**
   * ‏בוחר ערך, או מציג את ה-placeholder כשאין ערך.
   *
   * ‏value = "" אינו מספיק: האפשרות הריקה היא ``disabled``, ולכן הדפדפן
   * אינו יכול לבחור אותה — ‎selectedIndex‎ יוצא ‎-1‎ והתיבה מצוירת **ריקה**,
   * בלי ההזמנה לבחור. ‏selectedIndex = 0 מציג אותה, ואפשרות מושבתת עדיין
   * אינה ניתנת לבחירה ידנית.
   */
  function selectOrPlaceholder(sel, value) {
    if (!sel) return;
    if (value === "" || value === null || value === undefined) {
      sel.selectedIndex = 0;
      return;
    }
    sel.value = value;
    if (sel.selectedIndex < 0) sel.selectedIndex = 0;
  }

  function placeholderOption(label) {
    var opt = el("option", { attrs: { disabled: "disabled" }, text: label });
    // ‏כתכונה ולא דרך attrs: ‏el() מדלג על ערך ריק (‎v !== ""‎), ובלי זה
    // ערך האפשרות היה נופל לטקסט שלה — כלומר ‎select.value‎ היה מחזיר
    // "בחר/י מסלול" במקום "".
    opt.value = "";
    return opt;
  }

  function yearOptions() {
    var list = runtime.bootstrap ? pickList(runtime.bootstrap, ["years"], null) : [];
    var out = [];
    list.forEach(function (rec) {
      var y = num(rec.year, null);
      if (y === null) return;
      out.push({
        value: y,
        label:
          txt(rec.label) || YEAR_LABELS[y] || Tf("app.year.yearFallback", { year: y }),
      });
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
      return {
        value: y,
        label: YEAR_LABELS[y] || Tf("app.year.yearFallback", { year: y }),
      };
    });
  }

  function termOptions() {
    var list = runtime.bootstrap ? pickList(runtime.bootstrap, ["terms"], "term") : [];
    var out = [];
    list.forEach(function (rec) {
      var v = txt(rec.term);
      if (!v) return;
      out.push({
        value: v,
        label: txt(rec.label) || Tf("app.year.termFallback", { term: v }),
      });
    });
    return out.length ? out : TERMS_FALLBACK;
  }

  /* --- מצב הקטלוג: יש רשימת קורסים מהתוכנית, או בוחרים ישירות? ------- */

  /**
   * ‏``curriculum_available`` מהשרת. השדה חדש, ושרת שאינו מכיר אותו פשוט
   * לא שולח אותו — ואז התשובה היא ``null`` ("לא ידוע") והממשק מסיק מהרשימה.
   */
  /**
   * ‏למה אין תוכנית לימודים למסלול הנוכחי, לפי ``curriculum_absence``
   * שהשרת מחזיר. מוחזר כמפתח של ``app.terms.fallbackNote``.
   *
   * ‏הערך מגיע פר-מסלול ברשימת ``programs`` של ‏/api/bootstrap, כי החלפת
   * מסלול אינה מביאה את ‏bootstrap מחדש. בלי זה, מסלול שהמכללה כן מפרסמת
   * לו תוכנית — אבל לא בצורה שאפשר להציג — היה נראה בדיוק כמו מסלול שאין
   * לו תוכנית בכלל.
   */
  function curriculumAbsenceKey() {
    // ‏הבחירה בדפדפן מקדימה את ``programs``, שנקראה פעם אחת ב-bootstrap:
    // שם מתמטיקה שימושית תמיד ``intake_required``, כי בזמן הבקשה עוד לא
    // נבחר מועד. אחרי שבוחרים, המצב המקומי הוא שיודע.
    if (intakeMissing()) return "intake-required";
    var chosen = txt(state.program);
    var list = runtime.programs || [];
    for (var i = 0; i < list.length; i++) {
      if (txt(list[i].id) === chosen) {
        if (txt(list[i].curriculum_absence) === "intake_required") return "";
        return txt(list[i].curriculum_absence).replace(/_/g, "-");
      }
    }
    var boot = runtime.bootstrap || {};
    return txt(boot.curriculum_absence).replace(/_/g, "-");
  }

  /**
   * ‏האם השרת הזה שולף מהידיעון. ‏``features.fetch_on_demand`` הוא התשובה;
   * היעדרו פירושו "לא נאמר", ואז נשארים על ברירת המחדל המקומית.
   */
  function readFetchOnDemand(data) {
    var features = data && data.features;
    if (!features || typeof features !== "object") return runtime.canFetch;
    if (typeof features.fetch_on_demand === "boolean") return features.fetch_on_demand;
    return runtime.canFetch;
  }

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
    // לפני "אין תוכנית": יש שתיים, ורק לא נבחר מועד כניסה.
    if (intakeMissing()) return "intake-required";
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
  var FALLBACK_NOTE = T("app.terms.fallbackNote", {});

  var BROWSE_PLACEHOLDER = T("app.catalog.browsePlaceholder");

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
    return Tf("app.courses.unnamedCourse", { code: txt(code) });
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
    if (opts.unit) head = Tf("app.credits.withUnit", { value: head });
    if (!summary.unknown) return head;
    return Tf("app.credits.withMissing", {
      value: head,
      missing: missingCreditsText(summary.unknown, opts.short),
    });
  }

  function missingCreditsText(count, short) {
    if (short) return Tf("app.credits.missingShort", { count: count });
    return count === 1
      ? T("app.credits.missingOne", "")
      : Tf("app.credits.missingMany", { count: count });
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
      return T("app.courses.alternatives.placement");
    }
    // ‏61179+61180 למי שאין פטור מפיזיקה אקדמית, 61181 למי שיש. אחד מהשניים.
    if (txt(rec.physicsTrack)) {
      return T("app.courses.alternatives.physicsTrack");
    }
    // קורס ששייך למסלול התמחות מסוים. חלק מהמחלקות מפצלות סמסטרים לפי
    // מסלול, והכלי אינו יודע באיזה מסלול הסטודנט/ית — באזרחית הוא נקבע
    // לפי ציונים. מציגים, מסבירים, ולא מסמנים.
    // ‏מרגע שנבחרו התמחות או מסלול בשלב 1, השרת מסמן את הקורסים שלהם
    // ‏(``track_chosen``) ומוריד את אלה של האחרים.
    if (txt(rec.track) && !rec.trackChosen) {
      return Tf("app.courses.alternatives.track", { track: txt(rec.track) });
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
    // הבעלות היא על השלישייה מסלול+מועד+סמסטר. ראו ההערה ליד ``autoProgram``.
    var sameOwner =
      owned === target &&
      txt(state.autoProgram) === txt(state.program) &&
      txt(state.autoIntake) === txt(state.intake) &&
      txt(state.autoTrack) === trackSig();

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
            autoProgram: txt(state.program),
            autoIntake: txt(state.intake),
            autoTrack: trackSig(),
            autoCodes: adopted.slice(),
            // ‏הכול שלה. מרגע שאין סימון אוטומטי, אין "מומלץ שבוטל" —
            // יש רק מה שסומן ומה שלא.
            autoDropped: [],
            manualCodes: state.codes.slice(),
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
    if (owned && sameOwner && runtime.semesterCourses.length) return;

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
    var nextSemester = target && runtime.semesterCourses.length ? target : "";
    if (
      sameCodes(manual, state.codes) &&
      nextSemester === owned &&
      txt(state.autoProgram) === txt(state.program) &&
      txt(state.autoIntake) === txt(state.intake) &&
      txt(state.autoTrack) === trackSig() &&
      state.provenanceReady &&
      !claimAsManual
    ) {
      return;
    }

    // ‏החלפת התמחות או מסלול בלבד — אותו מסלול, מועד וסמסטר: מה שסומן
    // ‏מההמלצה הקודמת ונשאר מומלץ (קורסי הליבה) נשאר מסומן, וכך גם
    // ‏ה"בוטל" שלו. רק הקורסים של הבחירה הקודמת יורדים.
    var trackOnly =
      !!owned &&
      owned === nextSemester &&
      !claimAsManual &&
      txt(state.autoProgram) === txt(state.program) &&
      txt(state.autoIntake) === txt(state.intake) &&
      txt(state.autoTrack) !== trackSig();
    var stillRecommended = function (c) {
      return recommended.indexOf(c) !== -1 && state.autoCodes.indexOf(c) !== -1;
    };
    var keep = trackOnly
      ? state.codes.filter(function (c) {
          return manual.indexOf(c) !== -1 || stillRecommended(c);
        })
      : manual;

    // ‏codes: manual ולא next — ההמלצה **מוצגת** ואינה מסומנת. סטודנט/ית
    // שלא סימנה דבר לא בחרה דבר, ולכן אין לה מה לרשת. ``autoCodes`` נשאר
    // רשימת ההמלצה, כי ממנה מסומן הכול בלחיצה אחת.
    setState({
      codes: keep,
      provenanceReady: true,
      manualCodes: manual,
      autoSemester: nextSemester,
      autoProgram: nextSemester ? txt(state.program) : "",
      autoIntake: nextSemester ? txt(state.intake) : "",
      autoTrack: nextSemester ? trackSig() : "",
      autoCodes: recommended.slice(),
      autoDropped: trackOnly ? state.autoDropped.filter(stillRecommended) : [],
      activeSchedule: 0,
    });
    if (over.length) {
      toast(
        Tf("app.courses.tooManyCodes", {
          max: num(runtime.maxCodes, 0),
          codes: over.join(", "),
        }),
        "warn"
      );
    }
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
      autoProgram: txt(state.program),
      autoIntake: txt(state.intake),
      autoTrack: trackSig(),
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
        reason: rec ? "" : T("app.lecturers.deadEndReason"),
      };
    }
    return {
      ok: rec.ok !== false,
      reason: txt(rec.reason || T("app.lecturers.deadEndReason")),
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
        // ‏"no_groups" / "missing_data" / "semester_mismatch" מהשרת. הוא
        // מה שמאפשר לומר בלי רשת *מה* חסר, במקום להציע משיכה חוזרת.
        kind: txt(rec.kind),
        needs_scrape: rec.needs_scrape === true,
      });
    };
    runtime.notOffered.forEach(add);
    if (runtime.solve) pickList(runtime.solve, ["not_offered"], "code").forEach(add);
    return out;
  }

  /**
   * למה אין לקורס הזה קבוצות, בלשון שמתאימה לשרת שמציג אותה.
   *
   * ‏עם רשת נשארת הסיבה של השרת, שמדברת על הידיעון ועל משיכה חוזרת. בלי
   * רשת — המצב המאורח, שבו הכול בא מהקטלוג הלילי — אומרים את העובדה
   * עצמה: או שלא נפתחו קבוצות בסמסטר הזה, או שהקורס אינו בקטלוג.
   */
  function missingReason(rec, fallback) {
    if (!runtime.canFetch) {
      if (rec.kind === "no_groups") return T("app.lecturers.missing.reasonNoGroups");
      if (rec.kind === "missing_data") return T("app.lecturers.missing.reasonNotInCatalog");
    }
    if (rec.reason) return rec.reason;
    return fallback === undefined ? "" : fallback;
  }

  /**
   * ‏האם לכל קוד שנבחר כבר יש תשובה מהשרת — נתוני קבוצות, או הסבר מדוע
   * אין. ‏false כל עוד משהו בדרך, וזה בדיוק מה שמצדיק "ממתין".
   */
  function allSelectedAnswered() {
    if (!state.codes.length) return false;
    if (runtime.coursesBusy || !runtime.ready) return false;
    var explained = Object.create(null);
    notOfferedList().forEach(function (rec) {
      explained[rec.code] = true;
    });
    return state.codes.every(function (code) {
      var c = txt(code);
      return !!courseDataByCode(c) || explained[c] === true;
    });
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
        runtime.canFetch = readFetchOnDemand(data);
        // רשימת המסלולים. ברירת המחדל היא המסלול שיש לו קובץ תוכנית, כדי
        // שסטודנט/ית תוכנה לא תצטרך לבחור כלום; כל השאר בוחרים "אחר"
        // ומקבלים את הקטלוג המלא במקום רשימה של מחלקה זרה.
        if (Array.isArray(data.programs) && data.programs.length) {
          runtime.programs = data.programs;
        }
        applyBootstrapDefaults(data);
        fetchCatalogMeta();
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


  var appliedDefaults = false;

  /** ברירות מחדל מהפרופיל — רק כשאין מצב שמור. */
  function applyBootstrapDefaults(data) {
    if (appliedDefaults) return;
    appliedDefaults = true;

    var defaults = (data && data.defaults) || {};
    var profile = (data && data.profile) || {};
    var student = profile.student || {};
    var prefs = profile.preferences || {};

    // ‏נקודת הייחוס לסימון הסעיפים: מה שהיישום היה בוחר לסטודנט/ית הזה/ו
    // בלי שום קלט. נשמרת **תמיד**, גם כשיש מצב משוחזר — אחרת למי שחוזר/ת
    // לא היה מול מה להשוות, וזו בדיוק הנקודה שבה הסימון איבד את משמעותו.
    // ‏defaultState() הוא הגיבוי כשהשרת לא אמר דבר; אותה נוסחה בדיוק שבה
    // משתמש הגוש שמתחת, כדי ששני המקומות לא ייפרדו.
    var fallback = defaultState();
    var baseEarly = num(defaults.earliest, null);
    var baseLate = num(defaults.latest, null);
    runtime.baseline = {
      forbidFriday:
        defaults.forbid_friday === true || prefs.forbid_friday === true,
      earliest: baseEarly === null ? fallback.earliest : baseEarly,
      latest: baseLate === null ? fallback.latest : baseLate,
    };

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
      // ‏שנה וסמסטר **אינם** נקבעים כאן, בכוונה. ‏profile.json הוא הבחירה
      // של סטודנט/ית אחד/ת, ולהחיל אותה על כל מי שפותח/ת את הדף פירושו
      // לנחש זהות — וניחוש שנראה בדיוק כמו בחירה. ‏הן נשארות ריקות עד
      // שבוחרים, וההעדפות שמתחת (יעד ימים, שעות, שישי) כן נטענות: הן
      // ברירות מחדל סבירות ולא טענה על מי המשתמש/ת.
      // ‏יעד הימים **אינו** נקבע כאן, מאותה סיבה שהשנה והסמסטר אינם:
      // ‏profile.json הוא ההעדפה של סטודנט/ית אחת, ולהחיל אותה על כל מי
      // שפותח/ת את הדף פירושו לבחור בשמה. שאר ההעדפות כאן (שישה, שעות)
      // הן ברירות מחדל ניטרליות — "בלי הגבלה" — ולא דעה.
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

  /** החתימה של רשימת הסמסטר: מה שהשרת קיבל כשנשאל עליה. */
  function semesterKey() {
    return [txt(state.semester), txt(state.program), txt(state.intake), trackSig()].join("|");
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
      runtime.semesterCoursesFor = "";
      runtime.semesterNotes = null;
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
    var forKey = semesterKey();
    return getJSON(
      "/api/semester/" + encodeURIComponent(sem) + "/courses" +
        "?program=" + encodeURIComponent(state.program || "") +
        "&intake=" + encodeURIComponent(state.intake || "") +
        "&specialization=" + encodeURIComponent(chosenSpecialization()) +
        "&route=" + encodeURIComponent(chosenRoute())
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
        runtime.semesterCoursesFor = forKey;
        runtime.semesterNotes = (data && data.semester_notes) || null;
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
        var semInfo = (data && data.info) || {};
        // ‏false בלבד הוא אזהרה. ‏undefined פירושו "השרת לא אמר", וזה לא
        // אותו דבר — תוכנית שאין בה בדיקת סכום אינה תוכנית חשודה.
        runtime.semesterReconciles = semInfo.reconciles === false ? false : null;
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
        runtime.semesterCoursesFor = "";
        runtime.semesterNotes = null;
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
      track: txt(rec.track),
      // ‏הקורס שייך להתמחות/למסלול שנבחרו בשלב 1 — מומלץ כמו קורס ליבה.
      trackChosen: rec.track_chosen === true,
      // ‏"מחליף את …" — מטבלת ההחלפות של התוכנית: [{code, name}].
      replaces: Array.isArray(rec.replaces) ? rec.replaces : [],
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
      // רק לשם המוצג: קורס מתוכנית הלימודים נקרא כפי שהתוכנית מדפיסה אותו.
      program: txt(state.program),
      intake: txt(state.intake),
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
            kind: txt(rec.kind),
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
            kind: txt(rec.kind),
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
          // בלי רשת ``skip_all`` מדווח על כל קוד שהתבקש, וכתיבה לכאן הייתה
          // מוחקת את הסיבה האמיתית ("לא נפתחו קבוצות") ומחליפה אותה
          // ב"לא פנינו לידיעון" — על קורסים תקינים בדיוק כמו על חסרים.
          if (!runtime.canFetch) return;
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
      // ‏הודעת המצב של הידיעון על הקבוצה. שדה נפרד מ-``note``, שנושא
      // הערות שיוך וחובת נוכחות — ראו ``models.Group``.
      status_note: txt(rec.status_note),
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
    toast(reasons.join(" ") || T("app.toasts.pinReleased"), "warn");
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
      program: txt(state.program),
      intake: txt(state.intake),
      // ‏6 כשאין יעד: ‏days_penalty הוא ‎max(0, ימים - target)‎, ולכן 6 הוא
      // קנס אפס לכל מספר ימים — כלומר "בלי העדפה", ולא ניחוש. ‏4 היה
      // מעניש כל מערכת בת 5 ימים בשם בחירה שאיש לא עשה.
      target_days: num(state.targetDays, null) === null ? 6 : state.targetDays,
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
    // חישוב שאי אפשר לעצור הוא מסך נעול. ‏AbortController מבטל את
    // הבקשה עצמה, ולא רק מתעלם מהתשובה — אחרת השרת ממשיך לעבוד בזמן
    // שהמשתמש/ת כבר המשיכו הלאה.
    if (runtime.solveAbort) {
      try {
        runtime.solveAbort.abort();
      } catch (e) {
        /* דפדפן בלי abort — נופלים חזרה להתעלמות לפי seq */
      }
    }
    runtime.solveAbort =
      typeof AbortController === "function" ? new AbortController() : null;
    runtime.solveBusy = true;
    runtime.solveCancelled = false;
    render();
    return postJSON(
      "/api/solve",
      buildSolveBody(),
      runtime.solveAbort ? runtime.solveAbort.signal : undefined
    )
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
        if (err && err.name === "AbortError") {
          // ביטול אינו תקלה: אין באנר אדום, רק הודעה שקטה.
          runtime.solveError = null;
          runtime.solveCancelled = true;
          toast(T("app.schedule.solvingCancelled"), "ok");
        } else {
          runtime.solveError = errorText(err);
        }
        render();
      });
  }

  /** עוצר חישוב שרץ. הבחירות נשמרות — רק החישוב מפסיק. */
  function cancelSolve() {
    if (solveTimer) {
      clearTimeout(solveTimer);
      solveTimer = null;
    }
    seq.solve += 1; // תשובה שכבר בדרך תיזרק
    if (runtime.solveAbort) {
      try {
        runtime.solveAbort.abort();
      } catch (e) {
        /* מטופל ב-catch של doSolve */
      }
    }
    runtime.solveAbort = null;
    runtime.solveBusy = false;
    runtime.solveCancelled = true;
    render();
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
    // ‏בלי זהות אין למי לבנות. ‏/api/courses ו-/api/solve שולחים את
    // ``state.term`` כ-``semester``, ובקשה עם סמסטר ריק היא בקשה על
    // כלום — היא הייתה חוזרת ריקה ומציגה "לא נמצאה מערכת", כלומר תקלה
    // במקום הזמנה לבחור. יוצאים כאן, והמסך אומר מה חסר.
    if (!identityChosen()) {
      lastSig.semester = null;
      lastSig.courses = null;
      lastSig.program = null;
      return;
    }
    // גם המסלול, ולא רק הסמסטר: ‏/api/semester/<n>/courses מקבל ``?program=``
    // ומחזיר רשימה ריקה למסלול שאין לו תוכנית. בלי המסלול בחתימה החלפת
    // מסלול לא הייתה מושכת מחדש כלום, והרשימה של המסלול הקודם — כולל מה
    // שסומן ממנה — הייתה נשארת על המסך.
    // גם מועד הכניסה: אותו מספר סמסטר מציין קורסים אחרים בכל מועד, ולכן
    // החלפת מועד לבדה חייבת למשוך מחדש.
    // ‏וגם ההתמחות והמסלול: הם קובעים אילו קורסי מסלול מומלצים.
    var semSig =
      txt(state.semester) + "|" + txt(state.program) + "|" + txt(state.intake) +
      "|" + trackSig();
    if (force || semSig !== lastSig.semester) {
      lastSig.semester = semSig;
      fetchSemesterCourses();
    }
    // קבוצות הבחירה תלויות במסלול — ובמסלול עם מועדי כניסה גם במועד, כי
    // קובץ התוכנית (והאשכולות שבו) הוא קובץ לכל מועד.
    // ‏וגם בהתמחות, במסלול ובהתמחות המשנית: הם קובעים אילו חוקים ורשימות חלים.
    var electivesSig =
      txt(state.program) + "|" + txt(state.intake) + "|" + trackSig() + "|" + chosenSecondary();
    if (force || electivesSig !== lastSig.program) {
      lastSig.program = electivesSig;
      runtime.electives = null;
      runtime.electivesFor = "";
      fetchElectives();
    }
    var coursesSig = JSON.stringify([
      state.codes.slice().sort(),
      state.term,
      state.academicYear,
      // השמות המוצגים תלויים במסלול, ולכן החלפת מסלול מושכת אותם מחדש.
      txt(state.program),
      txt(state.intake),
    ]);
    if (force || coursesSig !== lastSig.courses) {
      lastSig.courses = coursesSig;
      fetchCourses();
    }
    scheduleSolve();
  }

  /* =====================================================================
   * 7. גיל הקטלוג  (catalog age)
   *
   * ‏עד לאריזה לאירוח ישב כאן רענון חי מול הידיעון: ‏startScrape, תשאול של
   * ‏/api/scrape/status, ויומן ששורותיו הוזרמו למסך. הכול הוסר יחד עם
   * ‏נקודות הקצה עצמן.
   *
   * ‏למה: לסטודנט/ית מאורח/ת אין גרידה משלהם ואין יומן לצפות בו, ולכן
   * ‏המצב שהממשק צריך לתאר הוא **"הקטלוג ישן"** ולא "הרענון שלך נכשל".
   * ‏HOSTING_NOTES.md §4 כלל 2. בנייה מחדש היא עכשיו עבודת cron, והשאלה
   * ‏היחידה שנשארה לממשק היא מתי היא רצה — ‏GET /api/catalog/meta.
   * ===================================================================== */

  function fetchCatalogMeta() {
    return getJSON("/api/catalog/meta")
      .then(function (data) {
        runtime.catalogMeta = data || null;
        renderHeader();
      })
      .catch(function () {
        // גיל הקטלוג הוא מידע משלים בלבד: כל שאר העמוד עובד בלעדיו. לכן
        // כישלון כאן אינו תקלה שמוצגת — התווית פשוט לא מופיעה.
        runtime.catalogMeta = null;
      });
  }

  /**
   * ‏התווית הצפה של שורת הטריות: ‏"הנתונים נמשכו מהידיעון ב-19.9.2026
   * ‏14:35 · 571 קורסים", ואחריה שורה שאומרת מה **לא** ידוע.
   *
   * ‏כאן, ולא בשורה עצמה, יושב כל הפירוט. השורה עונה על "האם לסמוך על
   * המסך"; התווית עונה על "מתי בדיוק, וכמה". ‏מספר הקורסים מגיע
   * מ-``/api/catalog/meta`` ולכן הוא מתאר את הקטלוג שמוגש — כשהוא עוד לא
   * נטען, או שאין קטלוג, הנוסח בלעדיו ולא עם אפס.
   *
   * ‏שורת ההערה אינה קישוט. ‏``src/shipped_catalog.py`` מחייב שכל נוסח
   * שנשען על הקטלוג ידבר על מתי הוא נמשך ולא ירמוז על מצב הידיעון החי,
   * והיא הדבר היחיד שאומר את זה עכשיו — קודם היא ישבה ב-``builtAtTitle``.
   */
  function updatedTitle(stamp) {
    var when = formatStampFull(txt(stamp));
    if (!when) return "";
    var meta = runtime.catalogMeta;
    var count = meta ? num(meta.course_count, null) : null;
    var head =
      count === null
        ? Tf("app.header.updatedTitleNoCount", { when: when })
        : Tf("app.header.updatedTitle", { when: when, count: count });
    return head + "\n" + T("app.header.updatedTitleNote");
  }

  /**
   * ‏ISO-8601 ב-UTC -> ‏"19.9.2026 14:35" בשעון המקומי. אותו סדר שבו
   * ‏``todayLabel()`` כותב תאריך, ועם שעה: התווית קיימת בשביל הדיוק
   * שהשורה מוותרת עליו, ותאריך בלי שעה מחזיר חצי ממנו.
   *
   * מחרוזת שאינה תאריך חוזרת כמות שהיא: עדיף להראות את מה שהשרת אמר
   * מאשר ‏"Invalid Date".
   */
  function formatStampFull(iso) {
    if (!iso) return "";
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      var pad = function (n) {
        return (n < 10 ? "0" : "") + n;
      };
      return (
        d.getDate() +
        "." +
        (d.getMonth() + 1) +
        "." +
        d.getFullYear() +
        " " +
        pad(d.getHours()) +
        ":" +
        pad(d.getMinutes())
      );
    } catch (e) {
      return iso;
    }
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
    ui.banners = byId("banners");
    ui.toasts = byId("toasts");
    ui.tplBanner = byId("tpl-banner");
    ui.tplToast = byId("tpl-toast");

    ui.selProgram = byId("select-program");
    ui.selIntake = byId("select-intake");
    ui.trackRow = byId("track-row");
    ui.fieldSpecialization = byId("field-specialization");
    ui.selSpecialization = byId("select-specialization");
    ui.labelSpecialization = byId("label-specialization");
    ui.fieldRoute = byId("field-route");
    ui.selRoute = byId("select-route");
    ui.labelRoute = byId("label-route");
    ui.fieldSecondary = byId("field-secondary");
    ui.selSecondary = byId("select-secondary");
    ui.specializationDeadline = byId("specialization-deadline");
    ui.fieldIntake = byId("field-intake");
    ui.selPlanSemester = byId("select-plan-semester");
    ui.fieldPlanSemester = byId("field-plan-semester");
    ui.fieldYear = byId("field-year");
    ui.fieldTerm = byId("field-term");
    ui.electives = byId("electives");
    ui.electivesNotes = byId("electives-notes");
    ui.electivesNeedsSpec = byId("electives-needs-spec");
    ui.electivesHeadNotes = byId("electives-head-notes");
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
    ui.semesterNote = byId("semester-note");
    ui.semesterInfo = byId("semester-info");
    ui.recommendedRow = byId("recommended-row");
    ui.recommendedTitle = byId("recommended-title");
    ui.recommendedNote = byId("recommended-note");
    ui.btnRestoreRecommended = byId("btn-restore-recommended");
    ui.advancedValues = byId("advanced-values");

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
    ui.daysWarning = byId("days-warning");
    ui.daysRelax = byId("days-relax");
    ui.daysRelaxTitle = byId("days-relax-title");
    ui.daysRelaxIntro = byId("days-relax-intro");
    ui.daysRelaxList = byId("days-relax-list");
    ui.daysRelaxNote = byId("days-relax-note");
    ui.inputEarliest = byId("input-earliest");
    ui.inputLatest = byId("input-latest");
    ui.chkFriday = byId("chk-forbid-friday");
    ui.blockedList = byId("blocked-list");

    ui.lectCourses = byId("lecturer-courses");
    ui.lectNote = byId("lecturers-note");
    ui.btnClearRanking = byId("btn-clear-ranking");

    ui.tabs = byId("schedule-tabs");
    ui.btnPrint = byId("btn-print");
    ui.settingsPills = byId("settings-pills");
    ui.summary = byId("schedule-summary");
    ui.legend = byId("schedule-legend");
    ui.unscheduled = byId("schedule-unscheduled");
    ui.gridScroll = byId("grid-scroll");
    ui.grid = byId("schedule-grid");
    ui.empty = byId("schedule-empty");
    ui.reasons = byId("infeasible-reasons");
    ui.suggestions = byId("infeasible-suggestions");
    ui.relax = byId("relax");
    ui.relaxTitle = byId("relax-title");
    ui.relaxIntro = byId("relax-intro");
    ui.relaxList = byId("relax-list");
    ui.relaxChecked = byId("relax-checked");
    ui.relaxUndo = byId("relax-undo");
    ui.scheduleNote = byId("schedule-note");
    ui.softBox = byId("soft-conflicts");
    ui.softTitle = byId("soft-conflicts-title");
    ui.softSub = byId("soft-conflicts-sub");
    ui.softList = byId("soft-conflicts-list");

    ui.themeToggle = byId("theme-toggle");
    ui.themeButtons = ui.themeToggle
      ? Array.prototype.slice.call(ui.themeToggle.querySelectorAll("[data-theme-choice]"))
      : [];

    ui.btnBuild = byId("btn-build");
    ui.stepsRoot = byId("steps");
    ui.printHead = byId("print-head");
    ui.detail = byId("meeting-detail");
    ui.detailBody = byId("meeting-detail-body");
    ui.btnDetailClose = byId("btn-detail-close");
    ui.compare = byId("compare");
    ui.compareBody = byId("compare-body");
    ui.techDetails = byId("tech-details");
    ui.techFacts = byId("tech-facts");
    ui.attendanceOff = byId("attendance-off");

    ui.stickyBar = byId("sticky-bar");
    ui.stickyTabs = byId("sticky-tabs");
    ui.stickyFacts = byId("sticky-facts");
    ui.btnShowGrid = byId("btn-show-grid");
    ui.overlay = byId("grid-overlay");
    ui.overlayPanel = byId("grid-overlay-panel");
    ui.overlayTabs = byId("overlay-tabs");
    ui.overlayFacts = byId("overlay-facts");
    ui.overlayLegend = byId("overlay-legend");
    ui.overlayGrid = byId("overlay-grid");
    ui.overlayGridScroll = byId("overlay-grid-scroll");
    ui.btnCloseGrid = byId("btn-close-grid");

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
    // שלב 5 אינו מתקפל, ולכן אין לו כפתור ואין לו שורת סיכום.
    ui.stepToggles = {};
    ui.stepSummaries = {};
    COLLAPSIBLE_STEPS.forEach(function (key) {
      ui.stepToggles[key] = byId("step-" + key + "-toggle");
      ui.stepSummaries[key] = byId("step-" + key + "-summary");
    });
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
        // מספר הסמסטר נגזר מלוח הסמסטרים של המסלול, ולכן הוא חייב להיגזר
        // מחדש כאן. בלי זה מסלול שאין לו תוכנית כלל היה ממשיך להצהיר
        // "סמסטר 5 בתוכנית הלימודים" שנשאר מהמסלול הקודם.
        // צורת הפונקציה בכוונה: ``semesterOf`` קורא את ``state.program``,
        // ולכן הוא חייב לרוץ אחרי שהוא כבר עודכן.
        setState(function (s) {
          s.program = txt(ui.selProgram.value);
          // מועד כניסה שייך למסלול שנבחר בו. החלפת מסלול מאפסת אותו,
          // אחרת "חורף" של מתמטיקה היה נשאר תלוי במסלול שאין לו מועדים
          // בכלל — וחוזר לתוקף בשקט בחזרה אליה.
          s.intake = "";
          // ‏וכך גם ההתמחות והמסלול: הם אפשרויות של המסלול הקודם.
          s.specialization = "";
          s.route = "";
          s.secondarySpecialization = "";
          // וכך גם מספר הסמסטר שנבחר לפי מועד: המספר שייך לתוכנית שבחרו
          // בה, והסמסטר הקלנדרי שנגזר ממנו אינו תקף למסלול אחר. מסלול
          // רגיל גוזר את שניהם מחדש משנה+סמסטר, כפי שתמיד עשה.
          if (usesPlanSemester()) {
            s.semester = "";
            s.term = "";
          } else {
            s.semester = semesterOf(s.studyYear, s.term);
          }
          s.activeSchedule = 0;
        });
      });
    }
    if (ui.selIntake) {
      ui.selIntake.addEventListener("change", function () {
        // מועד אחר הוא תוכנית אחרת לגמרי: אותו מספר סמסטר מציין בה
        // קורסים אחרים ולעיתים גם סמסטר קלנדרי אחר. הבחירה יורדת ונבחרת
        // מחדש מהרשימה של המועד החדש, ולא נגררת אליו.
        setState(function (s) {
          s.intake = txt(ui.selIntake.value);
          s.semester = "";
          s.term = "";
          s.activeSchedule = 0;
        });
      });
    }
    if (ui.selPlanSemester) {
      ui.selPlanSemester.addEventListener("change", function () {
        var picked = txt(ui.selPlanSemester.value);
        setState(function (s) {
          s.semester = picked;
          // ‏**הסמסטר הקלנדרי נגזר כאן ונשמר**, כי הוא מה שנשלח לשרת
          // כ-``semester`` בכל בקשת קורסים ופתרון. הוא נקרא מהתוכנית של
          // המועד שנבחר — ראו ``planTermFor``.
          s.term = planTermFor(picked);
          pruneTrackChoices(s);
          s.activeSchedule = 0;
        });
      });
    }
    if (ui.selSpecialization) {
      ui.selSpecialization.addEventListener("change", function () {
        setState(function (s) {
          s.specialization = txt(ui.selSpecialization.value);
          // מסלול ומשנית תלויים בהתמחות — מה שכבר אינו חל יורד.
          pruneTrackChoices(s);
          s.activeSchedule = 0;
        });
      });
    }
    if (ui.selRoute) {
      ui.selRoute.addEventListener("change", function () {
        setState(function (s) {
          s.route = txt(ui.selRoute.value);
          pruneTrackChoices(s);
          s.activeSchedule = 0;
        });
      });
    }
    if (ui.selSecondary) {
      ui.selSecondary.addEventListener("change", function () {
        setState({ secondarySpecialization: txt(ui.selSecondary.value) });
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
        toast(T("app.toasts.rankingCleared"), "ok");
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

    COLLAPSIBLE_STEPS.forEach(function (key) {
      watchFold(ui.steps[key]);
      var btn = ui.stepToggles[key];
      if (!btn) return;
      btn.addEventListener("click", function () {
        // שלב נעול אינו מציג כלום ואינו מקופל; לחיצה עליו לא תרשום העדפה
        // שתקפוץ ותקפל אותו ברגע שייפתח.
        var section = ui.steps[key];
        if (section && section.classList.contains("is-locked")) return;
        var next = !stepCollapsed(key);
        // בחירה מפורשת גוברת על הקיפול האוטומטי, ולתמיד: מרגע שנרשמה
        // כאן, ``autoCollapseIfIdle`` כבר לא נוגע בשלב הזה.
        state.collapsed[key] = next;
        runtime.autoCollapsed[key] = true;
        setState({ collapsed: state.collapsed }, { solve: false });
      });
    });

    ui.themeButtons.forEach(function (btn) {
      btn.dataset.fk = "theme-" + txt(btn.dataset.themeChoice);
      btn.addEventListener("click", function () {
        applyTheme(txt(btn.dataset.themeChoice));
      });
    });
    renderThemeToggle();

    if (ui.btnDetailClose) {
      ui.btnDetailClose.addEventListener("click", closeMeetingDetail);
    }
    if (ui.detail) {
      ui.detail.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") {
          ev.preventDefault();
          closeMeetingDetail();
        }
      });
    }
    if (ui.btnBuild) {
      // הכפתור עושה בדיוק את מה שכתוב עליו: מחשב מחדש, ואז לוקח אל התוצאה.
      ui.btnBuild.addEventListener("click", function () {
        doSolve();
        var target = ui.steps && ui.steps.schedule;
        if (target && target.scrollIntoView) {
          target.scrollIntoView({ block: "start" });
        }
      });
    }
    if (ui.btnShowGrid) {
      ui.btnShowGrid.addEventListener("click", openGridOverlay);
    }
    if (ui.btnCloseGrid) {
      ui.btnCloseGrid.addEventListener("click", closeGridOverlay);
    }
    if (ui.overlay) {
      // לחיצה על הרקע בלבד — לא על הפאנל עצמו.
      ui.overlay.addEventListener("mousedown", function (ev) {
        if (ev.target === ui.overlay) closeGridOverlay();
      });
    }
    if (ui.overlayPanel) {
      ui.overlayPanel.addEventListener("keydown", overlayKeydown);
    }
    watchStickyBar();

    // נגיעה ראשונה כלשהי בעמוד מכבה את הקיפול האוטומטי. ``capture`` כדי
    // שגם לחיצה שנעצרת בדרך תיספר, ו-``passive`` כדי לא לעכב גלילה.
    ["pointerdown", "keydown", "change"].forEach(function (evt) {
      document.addEventListener(
        evt,
        function () {
          runtime.userActed = true;
          // ‏תנועה רק בתגובה לפעולה (docs/DESIGN.md, עיקרון 3): קיפול
          // שקורה מעצמו בטעינה — שחזור מצב, ‏autoCollapseIfIdle — קופץ.
          if (ui.stepsRoot) ui.stepsRoot.classList.add("can-fold");
        },
        { capture: true, passive: true }
      );
    });
  }


  /**
   * ‏בזמן שגוף שלב נפתח, הוא חייב להיחתך בגבול השורה שגדלה — אחרת התוכן
   * נשפך על השלב הבא במשך האנימציה. אבל חיתוך קבוע היה חותך גם את מה
   * שיוצא מהגוף בכוונה כשהוא פתוח: רשימת תוצאות החיפוש וטבעות המיקוד.
   * ‏לכן ‎is-folding‎ חי רק מתחילת המעבר ועד סופו.
   */
  function watchFold(section) {
    var fold = section && section.querySelector(".step-fold");
    if (!fold) return;
    var mine = function (ev) {
      return ev.target === fold && ev.propertyName === "grid-template-rows";
    };
    fold.addEventListener("transitionrun", function (ev) {
      if (mine(ev)) fold.classList.add("is-folding");
    });
    ["transitionend", "transitioncancel"].forEach(function (evt) {
      fold.addEventListener(evt, function (ev) {
        if (mine(ev)) fold.classList.remove("is-folding");
      });
    });
  }

  /** האם השלב מקופל כרגע. מפתח חסר = פרוס. */
  function stepCollapsed(key) {
    return state.collapsed[key] === true;
  }

  /* =====================================================================
   * 8א. ערכת הצבעים
   * ===================================================================== */

  /**
   * הבחירה השמורה. "מערכת" נשמר כהיעדר ערך ולא כמחרוזת: כך אין מצב שבו
   * מפתח ישן קובע משהו אחר ממה ש-``theme.js`` יודע לקרוא, וכך גם שינוי של
   * מערכת ההפעלה בזמן שהעמוד פתוח נתפס בלי מאזין — פשוט אין תכונה שדורסת
   * את ‎prefers-color-scheme‎.
   */
  function readTheme() {
    var saved = null;
    try {
      saved = window.localStorage.getItem(THEME_KEY);
    } catch (e) {
      /* אחסון חסום — נשארים על "מערכת" */
    }
    return saved === "light" || saved === "dark" ? saved : "system";
  }

  function applyTheme(choice) {
    var next = THEME_CHOICES.indexOf(choice) === -1 ? "system" : choice;
    var root = document.documentElement;
    try {
      if (next === "system") window.localStorage.removeItem(THEME_KEY);
      else window.localStorage.setItem(THEME_KEY, next);
    } catch (e) {
      /* אחסון חסום — הבחירה תחול על הסשן הזה בלבד */
    }
    if (next === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", next);
    renderThemeToggle();
  }

  function renderThemeToggle() {
    if (!ui.themeButtons || !ui.themeButtons.length) return;
    var current = readTheme();
    ui.themeButtons.forEach(function (btn) {
      var mine = txt(btn.dataset.themeChoice);
      btn.setAttribute("aria-checked", mine === current ? "true" : "false");
    });
  }

  /* =====================================================================
   * 8ב. סרגל מצוף ושכבת המערכת
   * ===================================================================== */

  /**
   * הסרגל מופיע רק אחרי שחולפים על שלב 1.
   * ‏IntersectionObserver ולא מאזין scroll: הוא לא מריץ קוד בכל פיקסל של
   * גלילה, וזה משנה בעמוד שיש בו רשת של מאות תאים.
   */
  function watchStickyBar() {
    var first = ui.steps && ui.steps.year;
    if (!first || !ui.stickyBar) return;
    if (typeof window.IntersectionObserver !== "function") {
      // דפדפן בלי IO — הסרגל פשוט מוצג תמיד. עדיף מאשר שלא יופיע כלל.
      runtime.pastFirstStep = true;
      renderStickyBar();
      return;
    }
    var io = new window.IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          // ‏"חלפנו" = השלב כולו מעל קצה המסך העליון, ולא מתחת לו.
          runtime.pastFirstStep =
            !entry.isIntersecting && entry.boundingClientRect.bottom <= 0;
        });
        renderStickyBar();
      },
      { threshold: 0 }
    );
    io.observe(first);
  }

  /** שעת הסיום המאוחרת ביותר במערכת, בדקות. ‏null כשאין מפגשים. */
  function lastFinishOf(sch) {
    var latest = null;
    scheduleMeetings(sch).forEach(function (m) {
      var end = num(m.end, null);
      if (end !== null && (latest === null || end > latest)) latest = end;
    });
    return latest;
  }

  /** שלוש העובדות שהסרגל מחזיק. אותן עובדות בדיוק גם בשכבה. */
  /**
   * מה שהסרגל המצוף מחזיק: לא סטטיסטיקה.
   *
   * ‏"ימים 5 · שעת סיום 19:50 · זמן המתנה 3:00" הופיע גם כאן וגם בפאנל
   * שמתחת, ובשתי הלשוניות היה זהה — כלומר לא עזר לבחור ולא הוסיף מידע.
   * במקומו: מה מייחד את המערכת שנבחרה.
   */
  function stickyLabel(list, idx) {
    if (!list.length) return "";
    var labels = differentiators(list);
    return labels[clamp(idx, 0, labels.length - 1)] || "";
  }

  /** לשונית מוקטנת: המספר בלבד, והתיאור המלא ב-title ו-aria-label. */
  /** לשונית מוקטנת: המספר בלבד, והתיאור המבדיל ב-title וב-aria-label. */
  function compactTabs(box, list, prefix) {
    var labels = differentiators(list);
    list.forEach(function (sch, idx) {
      var label = Tf("app.sticky.tabLabel", {
        index: idx + 1,
        label: labels[idx],
      });
      box.appendChild(
        el("button", {
          class: "sticky-tab",
          attrs: {
            type: "button",
            role: "tab",
            "aria-selected": idx === state.activeSchedule ? "true" : "false",
            "aria-label": label,
            title: label,
          },
          data: { fk: prefix + idx },
          text: String(idx + 1),
          on: {
            click: function () {
              setState({ activeSchedule: idx }, { solve: false });
            },
          },
        })
      );
    });
  }

  function factChips(box, sch) {
    stickyFacts(sch).forEach(function (f) {
      box.appendChild(
        el("span", { class: "sticky-fact" }, [
          el("span", { class: "sticky-fact-label", text: f.label }),
          el("strong", { class: "sticky-fact-value ltr", text: f.value }),
        ])
      );
    });
  }

  /** המצב שהתחתית צוירה לפיו, כדי לא לבנות אותה מחדש בכל ‏render(). */
  var footerMode = null;

  /**
   * שורת התחתית, לפי ``mode`` של ‏/api/bootstrap.
   *
   * ‏``"hosted"``: שורה באנגלית עם שני קישורים (‏LinkedIn וטופס דיווח), שניהם
   * בלשונית חדשה. כל ערך אחר: המשפט המקומי. לפני ה-bootstrap, או כשהוא
   * נכשל, השורה נשארת ריקה — המשפט המקומי ("127.0.0.1 בלבד") שקרי בשרת
   * ציבורי, והמשפט המאורח מיותר במחשב של הסטודנט/ית.
   */
  function renderFooter() {
    var line = document.getElementById("app-footer-line");
    var boot = runtime.bootstrap;
    if (!line || !boot) return;
    var mode = boot.mode === "hosted" ? "hosted" : "local";
    if (mode === footerMode) return;
    footerMode = mode;
    clear(line);
    if (mode === "local") {
      line.removeAttribute("dir");
      line.removeAttribute("lang");
      setText(line, T("app.footer.local"));
      return;
    }
    // הנוסח המאורח הוא אנגלית בתוך דף ‏RTL. ‏dir/lang על השורה עצמה שומרים
    // על סדר הקטעים ועל ההגייה בקורא מסך.
    line.setAttribute("dir", "ltr");
    line.setAttribute("lang", "en");
    var link = function (text, href) {
      return el("a", {
        text: text,
        attrs: { href: href, target: "_blank", rel: "noopener" },
      });
    };
    var sep = function () {
      return document.createTextNode(" · ");
    };
    // ‏"Built by {author}": המשפט נשמר שלם ב-JSON, והשם מוחלף כאן בקישור.
    var builtBy = String(T("app.footer.hosted.builtBy")).split("{author}");
    line.appendChild(document.createTextNode(T("app.footer.hosted.brand")));
    line.appendChild(sep());
    line.appendChild(document.createTextNode(builtBy[0] || ""));
    line.appendChild(
      link(T("app.footer.hosted.author"), T("app.footer.hosted.authorUrl"))
    );
    line.appendChild(document.createTextNode(builtBy.slice(1).join("")));
    line.appendChild(sep());
    line.appendChild(document.createTextNode(T("app.footer.hosted.privacy")));
    line.appendChild(sep());
    line.appendChild(
      link(T("app.footer.hosted.report"), T("app.footer.hosted.reportUrl"))
    );
  }

  /**
   * מה שנועד למפתח/ת ולא לסטודנט/ית: זמן החישוב, גודל הקטלוג, מספר
   * הקבוצות, שנת הלימודים ויומן המשיכה.
   *
   * ‏**בלי ?debug=1 הבלוק אינו מוצג כלל.** קודם הוא היה מקופל בתחתית
   * העמוד וכל אחד יכול היה לפתוח אותו; אין בו שורה אחת שנועדה
   * לסטודנט/ית, ולכן הוא מוסתר, ו-?debug=1 גם חושף אותו וגם פותח אותו.
   * ה-``hidden`` הראשוני יושב בתבנית, כדי שלא יהבהב עד הציור הראשון.
   */
  function renderTechDetails() {
    setHidden(ui.techDetails, !DEBUG);
    if (!ui.techFacts) return;
    if (ui.techDetails && DEBUG) ui.techDetails.open = true;
    var s = runtime.solve;
    var boot = runtime.bootstrap;
    var cat = (boot && boot.catalog) || {};
    var bits = [];
    // ‏"נמצאו N מערכות אפשריות" נמחק יחד עם האריח שהציג את אותו מספר.
    // האזהרה שהספירה נקטעה נשארת: היא אומרת משהו על החיפוש עצמו.
    if (s && s.counts_truncated === true) bits.push(T("app.tech.truncated"));
    if (s && num(s.elapsed_ms, null) !== null) {
      bits.push(Tf("app.tech.elapsed", { ms: num(s.elapsed_ms, 0) }));
    }
    var db = (boot && boot.db) || {};
    if (num(db.count, null) !== null) {
      bits.push(Tf("app.header.metaCourses", { count: db.count }));
    }
    var groups = 0;
    runtime.courses.forEach(function (c) {
      groups += c.groups.length;
    });
    if (groups) bits.push(Tf("app.header.metaGroups", { count: groups }));
    if (num(cat.count, null) !== null) {
      bits.push(Tf("app.tech.catalog", { count: cat.count }));
    }
    if (txt(state.academicYear)) {
      bits.push(Tf("app.tech.academicYear", { year: txt(state.academicYear) }));
    }
    rebuild(ui.techFacts, function (box) {
      bits.forEach(function (line) {
        box.appendChild(el("li", { text: line }));
      });
    });
  }

  function renderStickyBar() {
    if (!ui.stickyBar) return;
    var list = schedules();
    var sch = activeSchedule();
    // אין מה לסכם לפני שיש פתרון, וגם לא בראש העמוד.
    var show = runtime.pastFirstStep === true && list.length > 0 && !!sch;
    setClass(ui.stickyBar, "is-visible", show);
    if (!show) return;
    if (ui.stickyTabs) {
      rebuild(ui.stickyTabs, function (box) {
        compactTabs(box, list, "bar-tab-");
      });
    }
    if (ui.stickyFacts) {
      rebuild(ui.stickyFacts, function (box) {
        var label = stickyLabel(list, state.activeSchedule);
        if (label) {
          box.appendChild(el("span", { class: "sticky-label", text: label }));
        }
      });
    }
  }

  function renderGridOverlay() {
    if (!ui.overlay || !runtime.overlayOpen) return;
    var list = schedules();
    var sch = activeSchedule();
    if (!sch) {
      closeGridOverlay();
      return;
    }
    if (ui.overlayTabs) {
      rebuild(ui.overlayTabs, function (box) {
        compactTabs(box, list, "ov-tab-");
      });
    }
    if (ui.overlayFacts) {
      rebuild(ui.overlayFacts, function (box) {
        var label = stickyLabel(list, state.activeSchedule);
        if (label) {
          box.appendChild(el("span", { class: "sticky-label", text: label }));
        }
      });
    }
    if (ui.overlayLegend) {
      rebuild(ui.overlayLegend, function (box) {
        buildLegend(box, sch);
      });
    }
    if (ui.overlayGrid) {
      rebuild(ui.overlayGrid, function (box) {
        buildGrid(box, sch, softConflictInfo(sch));
      });
      requestGridSizing();
    }
  }

  /** כל מה שאפשר להעביר אליו פוקוס בתוך השכבה, בסדר מסמך. */
  function focusableIn(root) {
    if (!root) return [];
    var nodes = root.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    return Array.prototype.filter.call(nodes, function (n) {
      return !n.disabled && n.offsetParent !== null;
    });
  }

  /** ‏Esc סוגר, ו-Tab מסתובב בתוך השכבה במקום לברוח לעמוד שמאחוריה. */
  function overlayKeydown(ev) {
    if (ev.key === "Escape") {
      ev.preventDefault();
      closeGridOverlay();
      return;
    }
    if (ev.key !== "Tab") return;
    var items = focusableIn(ui.overlayPanel);
    if (!items.length) return;
    var first = items[0];
    var last = items[items.length - 1];
    var active = document.activeElement;
    if (ev.shiftKey && (active === first || active === ui.overlayPanel)) {
      ev.preventDefault();
      last.focus();
    } else if (!ev.shiftKey && active === last) {
      ev.preventDefault();
      first.focus();
    }
  }

  function openGridOverlay() {
    if (!ui.overlay || runtime.overlayOpen) return;
    if (!activeSchedule()) return;
    runtime.overlayReturnTo = document.activeElement;
    runtime.overlayOpen = true;
    setHidden(ui.overlay, false);
    setClass(document.documentElement, "is-modal-open", true);
    renderGridOverlay();
    // הפוקוס נכנס לפאנל עצמו: קורא מסך מכריז את שם הדיאלוג, ומשם Tab
    // מתחיל מהפקד הראשון שבתוכו.
    if (ui.overlayPanel) ui.overlayPanel.focus();
  }

  function closeGridOverlay() {
    if (!ui.overlay || !runtime.overlayOpen) return;
    runtime.overlayOpen = false;
    setHidden(ui.overlay, true);
    setClass(document.documentElement, "is-modal-open", false);
    var back = runtime.overlayReturnTo;
    runtime.overlayReturnTo = null;
    // חזרה לכפתור שפתח — ובלי שהוא נעלם בינתיים, לכפתור שבסרגל.
    var target =
      back && back.isConnected && back.offsetParent !== null ? back : ui.btnShowGrid;
    if (target) {
      try {
        target.focus();
      } catch (e) {
        /* פוקוס נכשל — לא סיבה להשאיר את השכבה פתוחה */
      }
    }
  }

  function onYearTermChange() {
    // ‏תיבה שעדיין על ה-placeholder מחזירה "". ‏clamp(Math.round(null),1,4)
    // הוא 1, ולכן בחירת סמסטר לפני שנה הייתה קובעת בשקט "שנה א׳" — זהות
    // שאיש לא בחר, וזה בדיוק מה שהמסך הזה בא למנוע. ריק נשאר ריק.
    var rawYear = ui.selYear ? txt(ui.selYear.value) : "";
    var y =
      rawYear === ""
        ? num(state.studyYear, null)
        : clamp(Math.round(num(rawYear, 1)), 1, 4);
    var t = txt(ui.selTerm ? ui.selTerm.value : state.term) || txt(state.term);
    setState(function (s) {
      s.studyYear = y;
      s.term = t;
      s.semester = y === null || !t ? "" : semesterOf(y, t);
      // ‏התמחות שנבחרה בסמסטר 5 אינה חלה בסמסטר 1 — יורדת.
      pruneTrackChoices(s);
      s.activeSchedule = 0;
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
      el("button", { class: "banner-close", attrs: { type: "button", "aria-label": T("app.banners.closeLabel") }, text: "×" }),
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
        text: Tf("app.banners.bootstrapError", { error: runtime.bootstrapError }),
      });
    }
    if (runtime.coursesError) {
      wanted.push({
        key: "courses-error",
        kind: "error",
        text: Tf("app.banners.coursesError", { error: runtime.coursesError }),
      });
    }
    if (runtime.solveError) {
      wanted.push({
        key: "solve-error",
        kind: "error",
        text: Tf("app.banners.solveError", { error: runtime.solveError }),
      });
    }
    if (runtime.semesterError) {
      wanted.push({
        key: "semester-error",
        kind: "error",
        text: Tf("app.banners.semesterError", { error: runtime.semesterError }),
      });
    }

    // ‏המצב המאורח מדווח כל קוד שהתבקש כ"נדחה" — לא כי משהו נדחה, אלא כי
    // ‏אין שליפה בכלל. באנר שמציע "לנסות שוב" שם הוא הבטחה ריקה.
    if (runtime.canFetch && runtime.fetchSkipped.length) {
      var skippedCodes = runtime.fetchSkipped.map(function (rec) {
        return rec.code;
      });
      wanted.push({
        key: "fetch-skipped-" + skippedCodes.join(","),
        kind: "info",
        text: Tf("app.banners.fetchSkipped", { codes: skippedCodes.join(", ") }),
        action: {
          label: T("app.banners.fetchSkippedAction"),
          run: function () {
            retryAllMissing();
          },
        },
      });
    }

    // ---- נתונים ישנים ----------------------------------------------------
    // ‏store.freshness מוסיף כל קוד שנכשל לשתי הרשימות גם יחד, ולכן
    // ‏failed ⊆ stale **תמיד**. הצגת שתיהן זו לצד זו הייתה חוזרת על רוב
    // הקודים פעמיים; כאן יש רשימה מאוחדת אחת, וכשל מסומן בתוכה בסימן.
    // החלוקה הפנימית היא לפי מה שנוגע לסטודנט/ית — לא לפי סוג התקלה.
    // ‏רגע אחד שבו היומן מפסיק להיות פירוט טכני: כשהרענון נכשל. אז הוא
    // התשובה לשאלה "למה", ולכן הוא נפתח כאן ולא בתחתית העמוד.

    var db = (runtime.bootstrap && runtime.bootstrap.db) || {};
    var staleCodes = uniq(pickList(db, ["stale"], null).map(txt).filter(Boolean));
    var failedSet = Object.create(null);
    uniq(pickList(db, ["failed"], null).map(txt).filter(Boolean)).forEach(function (c) {
      failedSet[c] = true;
    });
    // ‏באנר **רק** כשקורס שנבחר בפועל מושפע. מסד ישן שאף קורס נבחר אינו
    // מושפע ממנו אינו הודעה שדורשת החלטה — הוא שורת מצב, והיא כבר בכותרת.
    // --- הקטלוג עצמו ישן ---
    // מה שידוע: מתי הוא נבנה. מה שאינו ידוע ואי אפשר לדעת: אם הידיעון
    // השתנה מאז. הניסוח אומר "ייתכן", ולא טוען דבר על השרת של המכללה.
    var builtAt = txt(db.catalog_built_at);
    var origin = txt(db.origin);
    if (builtAt && (origin === "shipped" || origin === "mixed")) {
      var ageDays = ageInDays(builtAt);
      if (ageDays !== null && ageDays >= CATALOG_STALE_DAYS) {
        wanted.push({
          key: "catalog-old-" + builtAt,
          kind: "warn",
          text: Tf("app.banners.catalogOld", { age: agoHebrew(builtAt) }),
          note: T("app.banners.catalogOldNote"),
        });
      }
    }

    var staleMine = [];
    if (staleCodes.length) {
      var chosenSet = Object.create(null);
      state.codes.forEach(function (c) {
        chosenSet[txt(c)] = true;
      });
      // קורס שהגיע עם הקטלוג אינו "הנתונים שלי התיישנו": כולם באותו
      // גיל בדיוק, כי כולם נבנו באותו רגע. רשימה של 572 קורסים "ישנים"
      // היא רעש, והמשפט "כדאי לעדכן מהידיעון" אינו נכון עבורם — יש
      // עליהם באנר אחד, על הקטלוג עצמו.
      var perCourse = (db.courses || {});
      staleMine = staleCodes.filter(function (c) {
        if (!chosenSet[c]) return false;
        var info = perCourse[c] || {};
        return txt(info.origin) !== "shipped";
      });
    }
    if (staleMine.length) {
      var staleSections = [
        {
          title: Tf("app.banners.stale.sectionMine", { count: staleMine.length }),
          codes: staleMine,
        },
      ];

      wanted.push({
        // ‏crc32 ולא רשימת הקודים עצמה: המפתח נכנס גם ל-data-fk, ומחרוזת
        // באורך מאות קודים שם היא רעש. הרגישות לשינוי בסט נשמרת.
        key: "stale-" + crc32(staleMine.join(",")),
        kind: "warn",
        // קוד ואז שם הקורס, כמו בשורות החפיפה. קוד לבדו אינו אומר לאיש
        // איזה קורס זה.
        text: Tf(
          staleMine.length === 1
            ? "app.banners.staleSelectedOne"
            : "app.banners.staleSelected",
          {
            count: staleMine.length,
            list: staleMine
              .map(function (code) {
                return Tf("app.banners.staleCourse", {
                  code: code,
                  name: nameOf(code),
                }).trim();
              })
              .join(", "),
          }
        ),
        details: {
          label: T("app.banners.stale.detailsLabel"),
          sections: staleSections,
          failed: failedSet,
          note: db.courses || {},
        },
      });
    }

    var s = runtime.solve;
    if (s && s.target_reachable === false && num(s.min_days, null) !== null) {
      wanted.push({
        key: "target-" + state.targetDays + "-" + s.min_days,
        kind: "warn",
        text:
          txt(s.target_message) ||
          Tf("app.banners.targetDays", {
            days: state.targetDays,
            min: s.min_days,
          }),
      });
    }
    if (s && pickList(s, ["tied_missing"], null).length) {
      var missingTied = pickList(s, ["tied_missing"], null).map(txt);
      wanted.push({
        key: "tied-" + missingTied.join(","),
        kind: "warn",
        text: Tf("app.banners.tiedMissing", { codes: missingTied.join(", ") }),
        action: {
          label: T("app.banners.tiedMissingAction"),
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
        text: T("app.banners.viabilityPartial"),
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

        var closeBtn = node.querySelector
          ? node.querySelector(".banner-close")
          : null;

        // הכל נכנס **לפני** כפתור הסגירה, כדי שה-× יישאר אחרון בשורה.
        function place(child) {
          if (!child) return;
          if (closeBtn) node.insertBefore(child, closeBtn);
          else node.appendChild(child);
        }

        // שורה שנייה, מושתקת: מה שהבאנר **אינו** יודע. היא נפרדת מהטקסט
        // ולא משורשרת אליו, כי היא הסתייגות ולא המשך של אותה טענה.
        if (item.note) {
          place(el("span", { class: "banner-note", text: item.note }));
        }

        if (item.details) place(bannerDetails(item));

        if (item.action) {
          place(
            el("button", {
              class: "btn btn-ghost btn-sm",
              attrs: { type: "button" },
              data: { fk: "banner-action-" + item.key },
              text: item.action.label,
              on: { click: item.action.run },
            })
          );
        }

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

  /**
   * הרשימה המלאה של הבאנר, מקופלת.
   * מצב הפתיחה נשמר ב-``runtime.bannerOpen`` ולא ב-DOM: ``renderBanners``
   * בונה את המכולה מחדש בכל ציור, ובזמן רענון זה קורה כל שתי שניות.
   */
  function bannerDetails(item) {
    var spec = item.details;
    if (!spec) return null;
    var hasSections = spec.sections && spec.sections.length;
    var hasLines = spec.lines && spec.lines.length;
    if (!hasSections && !hasLines) return null;

    var body = el("div", { class: "banner-more-body" });

    // שורות יומן גולמיות — לתקלות. אין כאן שבבי קודים, רק טקסט.
    if (hasLines) {
      var pre = el("pre", { class: "banner-more-log" });
      spec.lines.forEach(function (line) {
        pre.appendChild(el("div", { text: txt(line) }));
      });
      body.appendChild(pre);
    }
    var anyFailed = false;

    (spec.sections || []).forEach(function (section) {
      body.appendChild(el("p", { class: "banner-more-title", text: section.title }));
      var wrap = el("div", { class: "code-chips" });
      section.codes.forEach(function (code) {
        var isFailed = !!(spec.failed && spec.failed[code]);
        if (isFailed) anyFailed = true;
        var meta = (spec.note && spec.note[code]) || {};
        var reason = txt(meta.last_error);
        wrap.appendChild(
          el("span", {
            class: "code-chip" + (isFailed ? " is-failed" : ""),
            text: isFailed ? code + " ✕" : code,
            attrs: {
              title: isFailed
                ? reason
                  ? Tf("app.banners.details.fetchFailedWithReason", {
                      reason: reason,
                    })
                  : T("app.banners.details.fetchFailed")
                : txt(meta.age_text)
                ? Tf("app.banners.details.fetchedAge", {
                    age: txt(meta.age_text),
                  })
                : "",
            },
          })
        );
      });
      body.appendChild(wrap);
    });

    if (anyFailed) {
      body.appendChild(
        el("p", {
          class: "banner-more-legend",
          text: T("app.banners.details.failedLegend"),
        })
      );
    }

    var summary = el("summary", {
      class: "banner-more-summary",
      text: txt(spec.label) || T("app.banners.details.defaultLabel"),
      data: { fk: "banner-more-" + item.key },
    });

    var details = el("details", { class: "banner-more" }, [summary, body]);
    if (runtime.bannerOpen[item.key]) details.open = true;
    details.addEventListener("toggle", function () {
      runtime.bannerOpen[item.key] = details.open;
    });
    return details;
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
    renderStickyBar();
    renderCompare();
    renderTechDetails();
    renderFooter();
    markMissingStrings();
    // אחרי שלב 5 — הוא זה שמחשב את המערכת הפעילה, והשכבה מציגה אותה.
    renderGridOverlay();
  }

  /* --- כותרת: טריות, כפתורים, יומן ---------------------------------- */

  /**
   * טריות לפי מה שנבחר, ולא לפי כל המסד.
   *
   * ‏**באג של אוכלוסייה, לא של חישוב.** ‏``Store.freshness`` מדווח את
   * החותמת ה**ישנה ביותר** — כיוון בטוח, כי הוא נוטה להחמיר — אבל חישב
   * אותה על כל 572 הרשומות. התוצאה: הכותרת אמרה "הנתונים עודכנו לפני
   * 11 ימים" בזמן שששת הקורסים שנבחרו נשלפו באותו בוקר. הרשומה הישנה
   * ביותר במסד אינה תשובה לשאלה "כמה עדכני מה שאני רואה".
   *
   * הצבירה נשארת "הישן ביותר" ורק האוכלוסייה משתנה, ולכן הנטייה
   * להחמיר נשמרת: קורס נבחר אחד שלא רוענן מושך את כל השורה אחורה. זה
   * הכיוון הבטוח — מי שרואה "לפני 11 ימים" בטעות מרענן לחינם, ומי
   * שרואה "היום" בטעות בוטח בנתונים ישנים.
   *
   * Returns:
   *   ``{kind, stamp, stale}``. ‏``kind``: ‏``"none"`` (לא
   *   נבחר דבר), ‏``"fetched"`` (כל הנבחרים נשלפו כאן), ‏``"catalog"``
   *   (כולם מהקטלוג), ‏``"mixed"``, ‏``"unknown"`` (לקורס נבחר אין
   *   חותמת שימושית).
   *
   *   ‏``stamp`` היא החותמת ש**השורה בכותרת מדברת עליה**: הישנה מבין
   *   השליפות שנבחרו, הישנה מבין השתיים כש-``kind`` הוא ``"mixed"``,
   *   ותאריך בניית הקטלוג בכל השאר. ‏ISO-8601 גולמי ולא טקסט מוכן,
   *   כי הכותרת צריכה גם את הגיל היחסי, גם את התאריך המלא לתווית
   *   הצפה, וגם להשוות אותה מול ``max_age_hours`` — שלושה שימושים
   *   שאי אפשר לגזור ממחרוזת שכבר עברה ניסוח.
   */
  function selectedFreshness(db) {
    var perCourse = (db && db.courses) || {};
    var codes = state.codes || [];
    var stamps = [];
    var fromCatalog = 0;
    var noStamp = 0;
    var stale = false;

    codes.forEach(function (code) {
      var m = perCourse[txt(code)];
      // קוד שאין עליו מטא, או שמעולם לא נשלף בהצלחה, אינו "טרי" ואינו
      // "ישן" — הוא לא ידוע, וזה מספיק כדי לא לטעון עליו כלום.
      if (!m || m.known === false || !txt(m.fetched_at)) {
        noStamp += 1;
        stale = true;
        return;
      }
      if (m.stale === true) stale = true;
      if (txt(m.origin) === "shipped") {
        fromCatalog += 1;
        return;
      }
      stamps.push(txt(m.fetched_at));
    });

    var kind;
    if (!codes.length) kind = "none";
    else if (noStamp) kind = "unknown";
    else if (stamps.length && fromCatalog) kind = "mixed";
    else if (stamps.length) kind = "fetched";
    else kind = "catalog";

    // ‏ISO-8601 ב-UTC ממוין לקסיקוגרפית = כרונולוגית, כמו ב-store.py.
    var oldestFetch = stamps.length ? stamps.slice().sort()[0] : "";
    var builtStamp = txt(db && db.catalog_built_at);

    var stamp;
    if (kind === "fetched") stamp = oldestFetch;
    else if (kind === "mixed") {
      // הישנה מבין השתיים. ‏הצבירה נשארת "הישן ביותר" גם כאן, ומאותה
      // סיבה שהיא כזאת למעלה: מי שרואה תאריך ישן בטעות מרענן לחינם, ומי
      // שרואה תאריך טרי בטעות בוטח בנתונים ישנים.
      stamp = !builtStamp || (oldestFetch && oldestFetch < builtStamp)
        ? oldestFetch
        : builtStamp;
    } else stamp = builtStamp;

    return {
      kind: kind,
      stamp: stamp,
      stale: stale
    };
  }

  function renderHeader() {
    setHidden(ui.busy, !anyBusy());

    var boot = runtime.bootstrap;
    var db = (boot && boot.db) || {};
    var cat = (boot && boot.catalog) || {};

    var selFresh = selectedFreshness(db);

    // ‏**שורה אחת, ולא שתיים.** עד 2026-09-20 ישבו כאן שני משפטים זה מעל
    // זה — "הקטלוג נבנה לפני 19 שעות" ו-"הקטלוג נבנה ב-19 בספטמבר 2026 ·
    // ‏571 קורסים" — שאמרו את אותו דבר פעמיים, אחת מהן במילים של מי
    // שבונה את הקטלוג ולא של מי שמשתמש בו. הגיל היחסי הוא מה שסטודנט/ית
    // צריכים כדי להחליט אם לסמוך על המסך; התאריך המדויק ומספר הקורסים הם
    // פירוט, ופירוט מקומו בתווית הצפה.
    //
    // ‏הכול נגזר מחותמת אחת, ``selFresh.stamp`` — אותה חותמת לשורה,
    // לתווית ולמצב. שלוש תצוגות של אותו נתון אינן יכולות לסתור זו את זו.
    var stamp = txt(selFresh.stamp);
    var age = stamp ? agoHebrew(stamp) : "";

    // ‏מיושן = מה שהשורה מדווחת עליו חצה את ``SLOTWISE_MAX_AGE_HOURS``,
    // או שלקורס נבחר אין חותמת שימושית בכלל. אותו סף שהשרת מודד בו, ומאז
    // מיזוג "החדש מנצח" הוא נמדד מול תאריך בניית הקטלוג.
    var window_h = num(db.max_age_hours, 0);
    var ageHours = stamp ? ageInDays(stamp) * 24 : null;
    var stale =
      Boolean(selFresh.stale) ||
      (ageHours !== null && window_h > 0 && ageHours > window_h);

    // הנקודה נשאלת על אותה אוכלוסייה כמו השורה שלידה. קודם היא קראה את
    // ‏db.any_stale על כל המסד — ‏566 מתוך 572 מיושנים — ולכן הייתה
    // כתומה תמיד, גם ליד טקסט שאומר שהנתונים נשלפו לפני חצי שעה.
    var dotState = "unknown";
    if (boot) {
      if (!num(db.count, 0)) dotState = "empty";
      else if (stale) dotState = "stale";
      else dotState = "fresh";
    }
    if (ui.freshDot) ui.freshDot.setAttribute("data-state", dotState);

    // ‏db.text הוא **מוצא אחרון ותו לא**: הוא נגזר מהחותמת הישנה ביותר
    // ‏ב-data/db, והוא הטקסט שהראה "הנתונים עודכנו לאחרונה: 2026-09-01"
    // ‏ליד קטלוג שנבנה באותו לילה. מאז שהמיזוג ב-Store מעדיף את הקטלוג
    // כשהוא חדש יותר, השורה הזאת נבחרת רק כשאין קטלוג בכלל — ואז אין שום
    // דבר אחר לומר. ‏**אין להחזיר אותה כברירת מחדל.**
    var lineState = "";
    if (runtime.bootstrapError) {
      setText(ui.freshText, T("app.header.offline"));
      setTitle(ui.freshText, "");
    } else if (!boot) {
      setText(ui.freshText, T("app.header.loading"));
      setTitle(ui.freshText, "");
    } else if (!num(db.count, 0)) {
      setText(ui.freshText, T("app.header.empty"));
      setTitle(ui.freshText, "");
    } else if (age) {
      setText(ui.freshText, Tf("app.header.updated", { age: age }));
      setTitle(ui.freshText, updatedTitle(stamp));
      lineState = stale ? "stale" : "fresh";
    } else {
      setText(ui.freshText, txt(db.text));
      setTitle(ui.freshText, "");
    }
    if (ui.freshText) {
      if (lineState) ui.freshText.setAttribute("data-state", lineState);
      else ui.freshText.removeAttribute("data-state");
    }

    // שורת מצב אחת ותו לא. כל הספירות — כמה קורסים במסד, כמה קבוצות,
    // גודל הקטלוג, שנת הלימודים — הן פירוט טכני: הן מתארות את המסד ולא
    // את הבחירה של הסטודנט/ית, ו-"431 קורסים" ליד שם הקורס שלה מטעה.
    // מקומן ב"פרטים טכניים" שבתחתית, או בכותרת רק עם ?debug=1.
    var meta = [];
    if (DEBUG) {
      if (num(db.count, null) !== null) {
        meta.push(Tf("app.header.metaCourses", { count: db.count }));
      }
      var groups = 0;
      runtime.courses.forEach(function (c) {
        groups += c.groups.length;
      });
      if (groups) meta.push(Tf("app.header.metaGroups", { count: groups }));
      if (num(cat.count, null) !== null) {
        meta.push(Tf("app.tech.catalog", { count: cat.count }));
      }
      if (txt(state.academicYear)) meta.push(txt(state.academicYear));
    }
    setText(ui.freshMeta, meta.join(" · "));

    // ‏כאן ישבה פעם שורה שנייה, ‏#catalog-built, עם "הקטלוג נבנה ב-…".
    // ‏היא נמחקה ב-2026-09-20: היא חזרה על מה שהשורה שמעליה כבר אמרה,
    // והפירוט שהיה בה עבר לתווית ההצפה של ‏#freshness-text.
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
      ui.selProgram.appendChild(placeholderOption(T("ui.fields.programPlaceholder")));
      opts.forEach(function (o) {
        ui.selProgram.appendChild(
          el("option", { attrs: { value: txt(o.id) }, text: txt(o.label) || txt(o.id) })
        );
      });
    }
    // ‏אין ברירת מחדל למסלול. עד שבוחרים, התיבה מציגה הזמנה לבחור.
    selectOrPlaceholder(ui.selProgram, txt(state.program));
  }

  var programOptionsSig = null;

  /**
   * תיבת מועד הכניסה. מוצגת **רק** למסלול שיש לו ``intakes``, ומוסתרת
   * לכל השאר — כולל "תוכנית אחרת / לא ברשימה" וכולל מצב שלפני בחירת
   * מסלול. שאלה שאין לה משמעות למסלול שנבחר אינה שאלה.
   */
  function renderIntakeSelect() {
    if (!ui.selIntake || !ui.fieldIntake) return;
    var opts = programIntakes();
    if (!opts.length) {
      ui.fieldIntake.hidden = true;
      return;
    }
    ui.fieldIntake.hidden = false;
    var sig = JSON.stringify(opts);
    if (sig !== intakeOptionsSig) {
      intakeOptionsSig = sig;
      clear(ui.selIntake);
      ui.selIntake.appendChild(placeholderOption(T("ui.fields.intakePlaceholder")));
      opts.forEach(function (o) {
        ui.selIntake.appendChild(
          el("option", { attrs: { value: txt(o.id) }, text: txt(o.label) || txt(o.id) })
        );
      });
    }
    // אין ברירת מחדל: כל ניחוש כאן נכון לחצי מהמחלקה ושגוי לחצי השני.
    selectOrPlaceholder(ui.selIntake, txt(state.intake));
  }

  var intakeOptionsSig = null;

  /**
   * תיבת מספר הסמסטר, ומי משתי צורות השלב מוצגת.
   *
   * ‏מסלול עם מועדי כניסה מחליף את "שנת לימודים"+"סמסטר" בתיבה אחת,
   * ורק **אחרי** שנבחר מועד: לפני כן אין תוכנית, ולכן אין גם רשימת
   * סמסטרים למלא בה. שאר המסלולים אינם רואים את התיבה הזאת כלל ושתי
   * התיבות שלהם נשארות כפי שהיו.
   *
   * ‏מוסתרת ה**עטיפה**, לא ה-select: בדיקות קיימות קוראות את ערכן של
   * ‏#select-year ו-#select-term, וגם ``onYearTermChange`` קורא אותן.
   */
  function renderPlanSemesterSelect() {
    var uses = usesPlanSemester();
    if (ui.fieldYear) ui.fieldYear.hidden = uses;
    if (ui.fieldTerm) ui.fieldTerm.hidden = uses;
    if (!ui.selPlanSemester || !ui.fieldPlanSemester) return;
    // בלי מועד אין תוכנית ואין רשימה — התיבה מחכה לשורה שמעליה.
    var rows = uses && txt(state.intake) ? bootSemesters() : [];
    if (!rows.length) {
      ui.fieldPlanSemester.hidden = true;
      return;
    }
    ui.fieldPlanSemester.hidden = false;
    var sig = JSON.stringify(
      rows.map(function (r) {
        return [txt(r.semester), txt(r.label)];
      })
    );
    if (sig !== planSemesterOptionsSig) {
      planSemesterOptionsSig = sig;
      clear(ui.selPlanSemester);
      ui.selPlanSemester.appendChild(
        placeholderOption(T("ui.fields.planSemesterPlaceholder"))
      );
      rows.forEach(function (r) {
        // התווית היא מה שהשרת שלח — "סמסטר 4 · סמסטר א׳ (חורף)" — כדי
        // שהסמסטר הקלנדרי ייראה כאן, במקום שיתגלה רק אחר כך.
        ui.selPlanSemester.appendChild(
          el("option", {
            attrs: { value: txt(r.semester) },
            text: txt(r.label) || Tf("app.year.summaryPlanNoCount", { n: txt(r.semester) }),
          })
        );
      });
    }
    selectOrPlaceholder(ui.selPlanSemester, txt(state.semester));
  }

  var planSemesterOptionsSig = null;

  /** ממלא תיבה באפשרויות, רק כשהן השתנו, ובוחר את הערך או את ה-placeholder. */
  function fillSelect(sel, placeholder, options, value) {
    var sig = JSON.stringify([placeholder, options]);
    if (sel.dataset.sig !== sig) {
      sel.dataset.sig = sig;
      clear(sel);
      sel.appendChild(placeholderOption(placeholder));
      options.forEach(function (o) {
        sel.appendChild(el("option", { attrs: { value: o }, text: o }));
      });
    }
    selectOrPlaceholder(sel, value);
  }

  /**
   * ‏תיבות ההתמחות והמסלול (DESIGN.md, "Program, year and semester").
   *
   * ‏מוצגות רק למסלול שיש לו אותן, ורק מהסמסטר שבקובץ התוכנית: אזרחית
   * ‏ותעשייה וניהול מ-3, מכונות מ-5, חשמל מ-7. כשהן מוצגות הן חובה
   * ‏(מסגרת ‎--ink‎), אבל אינן נועלות את שאר השלבים — בלי בחירה הרשימה
   * ‏בשלב 2 היא זו של היום.
   */
  function renderTrackPickers() {
    if (!ui.trackRow) return;
    var spec = programSpec();
    var g = routeGroup();
    var showSpec = specializationShown();
    var showSecondary = secondaryShown();
    setHidden(ui.fieldSpecialization, !showSpec);
    setHidden(ui.fieldRoute, !g);
    setHidden(ui.fieldSecondary, !showSecondary);
    setHidden(ui.trackRow, !showSpec && !g && !showSecondary);
    var deadline = showSpec && spec ? txt(spec.deadline) : "";
    setText(ui.specializationDeadline, deadline);
    setHidden(ui.specializationDeadline, !deadline);
    if (!spec) return;

    // ‏בחשמל סוג התכן הנדסי קודם להתמחות, כמו ב-DESIGN.md; בשאר — ההתמחות
    // ‏קודמת, כי המסלול נשאל רק אחריה. סדר ה-DOM הוא גם סדר הטאב.
    var routeFirst = !!g && !(g.applies_to && (g.applies_to.specialization || []).length);
    var order = routeFirst
      ? [ui.fieldRoute, ui.fieldSpecialization, ui.fieldSecondary]
      : [ui.fieldSpecialization, ui.fieldRoute, ui.fieldSecondary];
    order.forEach(function (node, i) {
      if (node && ui.trackRow.children[i] !== node) {
        ui.trackRow.insertBefore(node, ui.trackRow.children[i] || null);
      }
    });

    if (showSpec) {
      setText(
        ui.labelSpecialization,
        spec.secondary ? T("ui.fields.specializationPrimary") : T("ui.fields.specialization")
      );
      fillSelect(
        ui.selSpecialization,
        T("ui.fields.specializationPlaceholder"),
        spec.options,
        chosenSpecialization()
      );
    }
    if (g) {
      setText(ui.labelRoute, routeLabel(g));
      fillSelect(ui.selRoute, T("ui.fields.routePlaceholder"), g.options || [], chosenRoute());
    }
    if (showSecondary) {
      fillSelect(
        ui.selSecondary,
        T("ui.fields.specializationPlaceholder"),
        secondaryOptions(),
        chosenSecondary()
      );
    }
  }

  /**
   * ‏כמה קורסים מומלצים בשבב של שלב 1: אותה רשימה ש"סמנו הכל" מסמן —
   * ‏רק של ההתמחות והמסלול שנבחרו, בלי חלופות ובלי קורסי התמחות אחרת.
   * ‏``course_count`` של ‏/api/bootstrap סופר את כל שורות הסמסטר, כולל של
   * ‏כל ההתמחויות, ולכן אינו המספר הזה. ‏null עד שהרשימה של הבחירה הנוכחית
   * ‏בידינו — אז השבב נשאר בלי מספר ולא מראה מספר של בחירה קודמת.
   */
  function recommendedCount() {
    if (!runtime.semesterCoursesFor || runtime.semesterCoursesFor !== semesterKey()) return null;
    return recommendedCodes().length;
  }

  function renderYearStep() {
    renderProgramSelect();
    renderIntakeSelect();
    renderPlanSemesterSelect();
    renderTrackPickers();
    if (!ui.selYear || !ui.selTerm) return;
    var years = yearOptions();
    var terms = termOptions();
    var sig = JSON.stringify([years, terms]);
    if (sig !== yearOptionsSig) {
      yearOptionsSig = sig;
      clear(ui.selYear);
      ui.selYear.appendChild(placeholderOption(T("ui.fields.studyYearPlaceholder")));
      years.forEach(function (y) {
        ui.selYear.appendChild(
          el("option", { attrs: { value: String(y.value) }, text: y.label })
        );
      });
      clear(ui.selTerm);
      ui.selTerm.appendChild(placeholderOption(T("ui.fields.termPlaceholder")));
      terms.forEach(function (t) {
        ui.selTerm.appendChild(
          el("option", { attrs: { value: t.value }, text: t.label })
        );
      });
    }
    selectOrPlaceholder(
      ui.selYear,
      num(state.studyYear, null) === null ? "" : String(state.studyYear)
    );
    selectOrPlaceholder(ui.selTerm, txt(state.term));

    // ‏לפני שיש זהות אין מה לסכם, ובוודאי לא "שנה ג׳ · סמסטר א" שאיש
    // לא בחר. השבב נעלם לגמרי: שורת המצב של הסעיף כבר אומרת מה חסר,
    // ואותו משפט פעמיים באותו מסך הוא בדיוק מה שרשימת הקבלה אוסרת.
    if (!identityChosen()) {
      setText(ui.semesterSummary, "");
      if (ui.semesterSummary) ui.semesterSummary.hidden = true;
      // ‏חריג אחד: מסלול עם מועדי כניסה שטרם הושלם. שם החוסר אינו "עוד
      // לא בחרו" סתמי אלא שאלה אחת קונקרטית — איזה מועד, או איזה סמסטר —
      // ולשורה הזאת יש מה לומר עליה. לכל שאר המסלולים היא נשארת ריקה,
      // כי שורת המצב של הסעיף כבר אומרת מה חסר.
      setText(
        ui.yearNote,
        !usesPlanSemester()
          ? ""
          : intakeMissing()
            ? FALLBACK_NOTE["intake-required"]
            : T("app.year.intakeNoSemester")
      );
      return;
    }
    if (ui.semesterSummary) ui.semesterSummary.hidden = false;

    var info = semesterInfo(state.semester);
    var count = recommendedCount();
    // ‏"סמסטר 4 · סמסטר א׳ (חורף)" — התווית שהשרת גוזר מהתוכנית. היא
    // מחליפה את "שנה ג׳" למסלול שאין לו שנה, ולכן היא גם מה שמוצג
    // בשבב וגם מה שמופיע באפשרויות התיבה.
    var planLabel = (info && txt(info.label)) || "";
    var yearLabel = usesPlanSemester()
      ? planLabel
      : YEAR_LABELS[state.studyYear] ||
        Tf("app.year.yearFallback", { year: state.studyYear });
    if (usesPlanSemester() && curriculumSemesterKnown()) {
      // מספר הסמסטר הוא מה שנבחר בתיבה, ולכן אין טעם לחזור עליו כאן
      // בנוסח "סמסטר 4 בתוכנית הלימודים". מה שהשבב מוסיף הוא הסמסטר
      // הקלנדרי — שנגזר ולא נבחר — וכמה קורסים יש בו.
      setText(
        ui.semesterSummary,
        count
          ? Tf("app.year.summaryIntakePlan", {
              label: planLabel,
              count: count,
            })
          : planLabel
      );
      setText(ui.yearNote, "");
    } else if (curriculumSemesterKnown()) {
      // ‏השנה והסמסטר כבר מופיעים בשורת המצב של הסעיף — שהיא גם שורת
      // הסיכום כשהוא מקופל. השבב הזה אמר בדיוק את אותו הדבר שורה מתחת,
      // ולכן הוא נושא רק את מה שאין שם: לאיזה סמסטר בתוכנית זה מתורגם,
      // וכמה קורסים מומלצים בו.
      setText(
        ui.semesterSummary,
        count
          ? Tf("app.year.summaryPlan", {
              n: txt(state.semester),
              count: count,
            })
          : Tf("app.year.summaryPlanNoCount", { n: txt(state.semester) })
      );
      setText(ui.yearNote, "");
    } else if (runtime.curriculumAvailable === false) {
      // אין תוכנית טעונה — הבחירה עצמה תקפה, ואסור לדבר על סמסטר
      // בתוכנית שאינה קיימת.
      setText(
        ui.semesterSummary,
        // ‏תווית התוכנית כבר נושאת את הסמסטר הקלנדרי, ולכן הוספתו כאן
        // שוב הייתה אומרת אותו פעמיים באותה שורה.
        usesPlanSemester()
          ? yearLabel
          : yearLabel + " · " + Tf("app.year.summaryTerm", { term: txt(state.term) })
      );
      // ‏"אין תוכנית" ו"יש תוכנית שאי אפשר להציג" הם שני מצבים שונים,
      // ועד כאן הם אמרו לסטודנט/ית בדיוק את אותו משפט.
      var absence = curriculumAbsenceKey();
      setText(
        ui.yearNote,
        FALLBACK_NOTE[absence] || FALLBACK_NOTE["no-curriculum"]
      );
    } else {
      // ‏מסלול עם מועדי כניסה אינו מגיע לכאן: בלי מועד ובלי מספר סמסטר
      // אין לו זהות בכלל, והוא יצא למעלה עם השורה שמבקשת אותם.
      setText(ui.semesterSummary, T("app.year.summaryNoPlan"));
      setText(
        ui.yearNote,
        txt(runtime.bootstrap && runtime.bootstrap.summer_note) ||
          T("app.year.noPlanNote")
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
        Tf(checked ? "app.courses.tiedToastAdded" : "app.courses.tiedToastRemoved", {
          courses: family.join(", "),
        }),
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
                ? T("app.courses.emptySemester")
                : T("app.courses.loading"),
            })
          );
        }
      });
    }

    // ‏SPEC §3: הסכום לעולם לא מציג 0 לנ"ז שאינה ידועה, ולעולם לא מסתיר
    // בשקט קורסים שאין להם נתון — הם נספרים בשורה שליד המונה.
    var credits = creditsSummary(state.codes);
    // בלי קורסים כלל הסכום הוא באמת 0. "—" שמור למצב שבו יש קורסים
    // ואין לאף אחד מהם נ"ז ידועות — שני דברים שונים לגמרי.
    var noneChosen = state.codes.length === 0;
    setText(
      ui.creditsTotal,
      Tf("ui.fields.creditsCounter", {
        credits: credits.known || noneChosen ? fmtNumber(credits.total) : "—",
      })
    );
    setText(
      ui.creditsUnknown,
      credits.unknown ? "(" + missingCreditsText(credits.unknown) + ")" : ""
    );
    setHidden(ui.creditsUnknown, !credits.unknown);

    renderSemesterNotes();
    renderRecommendedRow();
  }

  /** ‏"א, ב וג" — רשימה עברית קצרה. */
  function joinHe(items) {
    if (items.length < 2) return items.join("");
    return (
      items.slice(0, -1).join(", ") +
      " " +
      T("app.courses.semesterNotes.and") +
      items[items.length - 1]
    );
  }

  /**
   * ‏הפתק שבראש השלב, מ-``semester_slots`` של התוכנית: פתק זהב כשהתוכנית
   * ‏משבצת בסמסטר הזה קורסי בחירה או קורס כללי, ושורה שקטה אחת כשהיא
   * ‏אומרת "בכל סמסטר". הניסוח הוא של הנתונים: התווית ("קורס כללי 2"),
   * ‏ההערה, והציטוט מהשנתון.
   */
  function renderSemesterNotes() {
    var notes = runtime.semesterNotes || {};
    var live = !catalogFallbackActive() && runtime.semesterCoursesFor === semesterKey();
    var placed = live ? notes.placed || [] : [];
    var anywhere = live ? notes.anywhere || [] : [];

    // ‏``slot.note`` נשאר בנתונים ואינו מוצג: הפתק הוא שורה אחת (DESIGN.md,
    // ‏עיקרון 6).
    var what = [];
    placed.forEach(function (slot) {
      var kind = txt(slot.kind);
      var phrase =
        kind === "general" && txt(slot.label)
          ? Tf("app.courses.semesterNotes.placedKinds.generalLabel", { label: txt(slot.label) })
          : T("app.courses.semesterNotes.placedKinds." + kind, "");
      if (phrase && what.indexOf(phrase) === -1) what.push(phrase);
    });
    var gold = what.length
      ? Tf("app.courses.semesterNotes.placed", { what: joinHe(what) })
      : "";
    setText(ui.semesterNote, gold);
    setHidden(ui.semesterNote, !gold);

    var kinds = [];
    anywhere.forEach(function (slot) {
      var name = T("app.courses.semesterNotes.anywhereKinds." + txt(slot.kind), "");
      if (name && kinds.indexOf(name) === -1) kinds.push(name);
    });
    // ‏הציטוט מהשנתון נשאר בנתונים (``quote``); על המסך — שורה אחת.
    var info = kinds.length
      ? Tf("app.courses.semesterNotes.anywhere", { what: joinHe(kinds) })
      : "";
    setText(ui.semesterInfo, info);
    setHidden(ui.semesterInfo, !info);
  }

  /**
   * ‏"מומלצים לסמסטר X", ‏"לפי תכנית הלימודים" ו"סמנו הכל". מוסתר לגמרי
   * ‏במצב קטלוג ובקיץ — שם אין רשימת המלצה. הכרטיסים עצמם אומרים מה
   * ‏מסומן ולמה קורס אינו מומלץ, ולכן כאן אין עוד פסקה.
   */
  function renderRecommendedRow() {
    if (!ui.recommendedRow) return;
    var sem = txt(state.autoSemester);
    var show = !catalogFallbackActive() && !!sem && runtime.semesterCourses.length > 0;
    setHidden(ui.recommendedRow, !show);
    // ‏"סמנו הכל": מוצג כל עוד יש מומלץ שאינו מסומן. זה הופך הסכמה מלאה
    // לקליק אחד — והקליק הוא שלה.
    var picked = selectedSet();
    var anyUnpicked = (state.autoCodes || []).some(function (c) {
      return picked[txt(c)] !== true;
    });
    setHidden(ui.btnRestoreRecommended, !show || !anyUnpicked);
    setText(ui.recommendedTitle, show ? Tf("app.courses.recommended.heading", { semester: sem }) : "");

    // ‏הסתייגות, לא תקלה: מספר הנ"ז שחולץ מהשנתון אינו שווה לסה"כ שהשנתון
    // עצמו מדפיס לסמסטר הזה. שורה אחת בלבד (DESIGN.md, עיקרון 6): ההסבר
    // המלא נשאר ב-``note`` של הסמסטר ובקובץ docs/PROGRAM_REVIEW.md.
    var mismatch =
      show && runtime.semesterReconciles === false
        ? T("app.courses.recommended.creditsMismatch")
        : "";
    setText(ui.recommendedNote, mismatch);
    setHidden(ui.recommendedNote, !mismatch);
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
    var reason = src
      ? missingReason({ kind: txt(src.kind), reason: txt(src.reason) })
      : "";

    // ‏שרת בלי רשת (המצב המאורח) מדווח **כל** קוד שהתבקש כ"נדחה לרגע",
    // כי ``skip_all`` תולה את אותו משפט על כל הרשימה. זו אינה דחייה
    // זמנית אלא המצב הקבוע, ולכן התווית "נדחה לרגע" והכפתור שאחריה
    // הופיעו על קורסים תקינים לגמרי. בלי רשת הסימון הזה חסר משמעות.
    if (!runtime.canFetch && name === "skipped") name = have ? "" : "unavailable";

    if (!have && (runtime.fetching[c] || (selected && (runtime.coursesBusy || !runtime.ready)))) {
      return {
        state: "loading",
        tag: T("app.courses.status.loadingTag"),
        tagClass: "",
        text: T("app.courses.status.loadingText"),
        retry: false,
      };
    }
    if (name === "unavailable") {
      // בלי רשת אין "אפשר לנסות שוב": נאמרת הסיבה, וזה הכול.
      return {
        state: "unavailable",
        tag: T("app.courses.status.unavailableTag"),
        tagClass: "tag--warn",
        text: runtime.canFetch
          ? Tf("app.courses.status.unavailableText", {
              reason: reason || T("app.courses.status.unavailableReason"),
            })
          : reason || T("app.courses.status.offlineText"),
        retry: runtime.canFetch,
      };
    }
    if (name === "skipped") {
      return {
        state: "skipped",
        tag: T("app.courses.status.skippedTag"),
        tagClass: "tag--warn",
        text: Tf("app.courses.status.skippedText", {
          reason: reason || T("app.courses.status.skippedReason"),
        }),
        retry: runtime.canFetch,
      };
    }
    if (have) {
      return name === "fetched"
        ? {
            state: "fetched",
            tag: T("app.courses.status.fetchedTag"),
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
        tag: T("app.courses.status.noneTag"),
        tagClass: "tag--warn",
        text: T("app.courses.status.noneText"),
        retry: false,
      };
    }
    return {
      state: "pending",
      tag: runtime.canFetch
        ? T("app.courses.status.pendingTag")
        : T("app.courses.status.offlineTag"),
      tagClass: "tag--warn",
      // "אפשר לבקש משיכה נוספת מהידיעון" נכון רק כשיש ממי לבקש.
      text: runtime.canFetch
        ? T("app.courses.status.pendingText")
        : T("app.courses.status.offlineText"),
      retry: runtime.canFetch,
    };
  }

  function retryButton(code, label) {
    return el("button", {
      class: "btn btn-ghost btn-sm",
      attrs: { type: "button", title: T("app.courses.retryTitle") },
      data: { fk: "retry-" + txt(code) },
      text: label || T("app.courses.retryButton"),
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
   * כרטיס קורס אחד (DESIGN.md, "Course card"): תיבת סימון, שם וקוד, נ"ז
   * בסוף; שורה אחת של מבנה השיעורים וקורסי הקדם; ושורה אופציונלית של
   * ‏"מחליף את …". כרטיס נבחר מקבל את צבע הקורס — אותו צבע שיהיה לו במערכת.
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
    var family = tiedGroupFor(code);
    var tied = family.length > 1;

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
      el("span", { class: "course-title" }, [
        el("span", { class: "course-name", text: txt(rec.name) }),
        el("span", { class: "course-code", text: code }),
      ]),
    ]);

    // ‏השורה האחת: מבנה השיעורים וקורסי הקדם.
    var hours = [];
    if (num(rec.he, 0)) {
      hours.push(Tf("app.courses.hours.lecture", { n: fmtNumber(rec.he) }));
    }
    if (num(rec.te, 0)) {
      hours.push(Tf("app.courses.hours.tutorial", { n: fmtNumber(rec.te) }));
    }
    if (num(rec.ma, 0)) {
      hours.push(Tf("app.courses.hours.lab", { n: fmtNumber(rec.ma) }));
    }
    if (num(rec.pr, 0)) {
      hours.push(Tf("app.courses.hours.project", { n: fmtNumber(rec.pr) }));
    }
    var meta = [];
    if (hours.length) meta.push(hours.join(" · "));
    if (rec.prereq && rec.prereq.length) {
      meta.push(Tf("app.courses.prereq", { list: rec.prereq.join(", ") }));
    }
    if (meta.length) {
      main.appendChild(el("span", { class: "course-meta", text: meta.join(" | ") }));
    }

    // ‏"מחליף את …": מטבלת ההחלפות, ובלעדיה הערת התוכנית שאומרת זאת.
    // ‏הערה של קורס צמוד ("חובה בצמוד ל-…") יורדת — "נבחר יחד עם" אומר אותה.
    var replaces = (rec.replaces || [])
      .map(function (r) {
        return [txt(r.code), txt(r.name)].filter(Boolean).join(" ");
      })
      .filter(Boolean);
    var note = txt(rec.note);
    if (replaces.length) {
      main.appendChild(
        el("span", {
          class: "course-meta course-replaces",
          text: Tf("app.courses.replaces", { course: replaces.join(", ") }),
        })
      );
      if (/^מחליף/.test(note)) note = "";
    } else if (/^מחליף/.test(note)) {
      main.appendChild(el("span", { class: "course-meta course-replaces", text: note }));
      note = "";
    }
    if (!note) note = ruleCourseNotes()[code] || "";
    if (note && !tied) {
      main.appendChild(el("span", { class: "course-meta", text: note }));
    }
    if (tied) {
      main.appendChild(
        el("span", {
          class: "course-meta course-tied-with",
          text: Tf("app.courses.tiedWith", {
            courses: family
              .filter(function (c) {
                return c !== code;
              })
              .join(", "),
          }),
        })
      );
    }
    if (altReason) {
      main.appendChild(el("span", { class: "course-meta", text: altReason }));
    }

    var tags = el("div", { class: "course-tags" });
    if (rec.fromCatalog) {
      tags.appendChild(
        el("span", {
          class: "tag " + (rec.in_curriculum ? "tag--in-plan" : "tag--out-plan"),
          text: rec.in_curriculum
            ? T("app.courses.tags.inCurriculum")
            : T("app.courses.tags.fromCatalog"),
        })
      );
    } else if (isExtra && electiveCodes()[code]) {
      // ‏קורס מרשימות הבחירה של התוכנית אינו "מחוץ לסמסטר": כך בוחרים בחירה.
      tags.appendChild(
        el("span", { class: "tag tag--in-plan", text: T("app.courses.tags.elective") })
      );
    } else if (isExtra) {
      tags.appendChild(
        el("span", {
          class: "tag tag--out-plan",
          text: rec.fromSemester
            ? Tf("app.courses.tags.fromSemester", { semester: rec.fromSemester })
            : T("app.courses.tags.outsideSemester"),
        })
      );
    }
    if (tied) {
      tags.appendChild(
        el("span", { class: "tag tag--tied", text: T("app.courses.tags.tied") })
      );
    }
    // ‏חובה רק בהתמחות שנבחרה — ולא קורס של מסלול (סוג תכן, התנסות מעשית).
    // ‏וקורס שהתוכנית קובעת כחובה בהתמחות בלי לשבץ אותו בסמסטר — גם
    // ‏כשנוסף מהבחירה או מהחיפוש.
    var mySpec = chosenSpecialization();
    var specTrack =
      !isExtra && rec.trackChosen && txt(rec.track).split(" / ").indexOf(mySpec) !== -1;
    if (mySpec && (specTrack || specMandatoryCodes()[code])) {
      tags.appendChild(
        el("span", {
          class: "tag tag--spec",
          text: Tf("app.courses.tags.specialization", { name: mySpec }),
        })
      );
    }
    if (altReason) {
      tags.appendChild(
        el("span", {
          class: "tag tag--warn",
          // בקורס של מסלול התמחות שם המסלול הוא המידע השימושי; בשאר
          // החלופות אין שם קצר, ו"חלופה" הוא מה שיש לומר.
          text: txt(rec.track) ? txt(rec.track) : T("app.courses.tags.alternative"),
        })
      );
    }
    if (unavailable) {
      tags.appendChild(
        el("span", { class: "tag tag--dead", text: T("app.courses.tags.notOffered") })
      );
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

    // ‏SPEC §3: "—" ולא "0" — 86% מהקטלוג אינו בתוכנית, ואין לו נ"ז שמורות.
    var creditsNode = el("span", {
      class: "course-credits",
      text: Tf("app.courses.creditsUnit", { credits: fmtCredits(rec.credits) }),
    });

    var cls = "course-item";
    if (checked) cls += " is-selected c" + colorOf(code);
    if (tied) cls += " is-tied";
    if (unavailable) cls += " is-unavailable";

    // ‏<label> — לחיצה בכל מקום בכרטיס מחליפה את תיבת הסימון, בלי כפל אירועים.
    return el(
      "label",
      {
        class: cls,
        attrs: { title: unavailable ? T("app.courses.notOfferedTitle") : "" },
        style: { "--course-idx": String(colorOf(code)) },
      },
      [box, main, creditsNode]
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
        box.appendChild(el("li", { text: T("app.search.searching") }));
        return;
      }
      if (runtime.catalogError) {
        box.appendChild(
          el("li", { text: Tf("app.search.failed", { error: runtime.catalogError }) })
        );
        return;
      }
      if (!results.length) {
        box.appendChild(el("li", { text: T("app.search.noResults") }));
        return;
      }
      var selected = selectedSet();
      results.forEach(function (rec) {
        var already = selected[rec.code] === true;
        var tag = rec.in_curriculum
          ? rec.curriculum_semester
            ? Tf("app.search.tags.inPlanSemester", {
                semester: rec.curriculum_semester,
              })
            : T("app.search.tags.inPlan")
          : T("app.search.tags.outOfPlan");
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
          li.appendChild(
            el("span", { class: "tag", text: T("app.search.alreadySelected") })
          );
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
  // דרישות הבחירה: החוקים ורשימות הבחירה של התוכנית, לפי ההתמחות
  // ======================================================================
  function fetchElectives() {
    var program = txt(state.program);
    var key = [program, txt(state.intake), trackSig(), chosenSecondary()].join("|");
    if (!program || program === "other") {
      runtime.electives = { available: false };
      runtime.electivesFor = key;
      return Promise.resolve();
    }
    if (runtime.electivesFor === key && runtime.electives) return Promise.resolve();
    runtime.electivesFor = key;
    runtime.electivesBusy = true;
    var my = ++seq.electives;
    return getJSON(
      "/api/program/electives?program=" + encodeURIComponent(program) +
        "&intake=" + encodeURIComponent(txt(state.intake)) +
        "&specialization=" + encodeURIComponent(chosenSpecialization()) +
        "&route=" + encodeURIComponent(chosenRoute()) +
        "&secondary=" + encodeURIComponent(chosenSecondary())
    )
      .then(function (data) {
        if (my !== seq.electives) return; // תשובה ישנה — מתעלמים
        runtime.electivesBusy = false;
        runtime.electives = data || { available: false };
        render();
      })
      .catch(function () {
        if (my !== seq.electives) return;
        runtime.electivesBusy = false;
        // כישלון רשת אינו "אין דרישות" — מסתירים, ולא ממציאים.
        runtime.electives = { available: false };
        runtime.electivesFor = "";
        render();
      });
  }

  /**
   * ‏{קוד: true} לקורסים שחובה בהתמחות שנבחרה אף שאינם בשום סמסטר
   * ‏(``mandatory_in_specialization``; באזרחית, ניהול הבנייה: 500210, 51600).
   */
  function specMandatoryCodes() {
    var out = Object.create(null);
    var data = runtime.electives;
    ((data && data.available && data.rules) || []).forEach(function (rule) {
      if (txt(rule.type) !== "mandatory_in_specialization") return;
      (rule.codes || []).forEach(function (c) {
        if (txt(c)) out[txt(c)] = true;
      });
    });
    return out;
  }

  /** ‏{קוד: שורה} — הערת כרטיס מחוק שחל (``course_notes``; ‏51170). */
  function ruleCourseNotes() {
    var out = Object.create(null);
    var data = runtime.electives;
    ((data && data.available && data.rules) || []).forEach(function (rule) {
      var notes = rule.course_notes || {};
      Object.keys(notes).forEach(function (c) {
        if (txt(notes[c]) && !out[c]) out[c] = txt(notes[c]);
      });
    });
    return out;
  }

  /** ‏{קוד: true} לכל קורס ברשימות הבחירה שמוצגות עכשיו. */
  function electiveCodes() {
    var out = Object.create(null);
    var data = runtime.electives;
    ((data && data.available && data.clusters) || []).forEach(function (cluster) {
      (cluster.courses || []).forEach(function (course) {
        if (txt(course.code)) out[txt(course.code)] = true;
      });
    });
    return out;
  }

  /**
   * ‏שורות הזהב שתחת כל אשכול (DESIGN.md, "Which rules are shown"):
   * ‏שורת הרכב אחת לרשימה, ו"אפשר לקחת רק אחד מ-A ו-B" לכל חוק
   * ‏"רק אחד מ-" שחל (``mutually_exclusive``, ``only_one_counts``) — תחת
   * ‏כל אשכול שמחזיק לפחות אחד מהקורסים של החוק.
   * ‏מחזירה {מפתח-אשכול: [שורות]}.
   */
  function clusterNotes(data) {
    var out = Object.create(null);
    // ‏חוקי הרכב: מינימום על חלק מרשימה אחת (``where``). כל החוקים של אותה
    // ‏רשימה מצטרפים לשורה אחת, בלשון הנתונים: "מתוכם לפחות 3 מתחום החומרה
    // ‏ולפחות 3 מתחום התוכנה".
    var composition = Object.create(null);
    (data.rules || []).forEach(function (rule) {
      if (txt(rule.type) !== "min_courses" || !rule.partial) return;
      if ((rule.lists || []).length !== 1 || !txt(rule.text)) return;
      var key = txt(rule.lists[0]);
      composition[key] = composition[key] || [];
      composition[key].push(txt(rule.text));
    });
    Object.keys(composition).forEach(function (key) {
      out[key] = [composition[key].join(" ")];
    });
    // ‏חוק מילולי שהנתונים מסמנים ``show`` ויש לו רשימה: תחת הרשימה.
    (data.rules || []).forEach(function (rule) {
      if (!rule.show || !txt(rule.text)) return;
      (rule.lists || []).forEach(function (name) {
        var key = txt(name);
        out[key] = out[key] || [];
        if (out[key].indexOf(txt(rule.text)) === -1) out[key].push(txt(rule.text));
      });
    });

    (data.rules || []).forEach(function (rule) {
      var type = txt(rule.type);
      if (type !== "mutually_exclusive" && type !== "only_one_counts") return;
      var codes = Object.keys(rule.rows || {}).sort(function (a, b) {
        return num(a, 0) - num(b, 0);
      });
      if (codes.length < 2) return;
      var line = Tf("app.electives.onlyOne", {
        codes: codes.slice(0, -1).join(", ") + " ו-" + codes[codes.length - 1],
      });
      (data.clusters || []).forEach(function (cluster) {
        var holds = (cluster.courses || []).some(function (course) {
          return codes.indexOf(txt(course.code)) !== -1;
        });
        if (!holds) return;
        var key = txt(cluster.key);
        out[key] = out[key] || [];
        if (out[key].indexOf(line) === -1) out[key].push(line);
      });
    });
    return out;
  }

  function pillText(pill) {
    var n = num(pill.n, 0);
    var shown = fmtNumber(n);
    switch (txt(pill.type)) {
      case "min_courses":
      case "min_total_courses":
        return n === 1
          ? T("app.electives.pills.minCoursesOne")
          : Tf("app.electives.pills.minCourses", { n: shown });
      case "min_credits":
        return Tf(
          pill.approximate ? "app.electives.pills.minCreditsApprox" : "app.electives.pills.minCredits",
          { n: shown }
        );
      case "exact_courses":
        return n === 1
          ? T("app.electives.pills.exactCoursesOne")
          : Tf("app.electives.pills.exactCourses", { n: shown });
      case "max_credits":
        return Tf("app.electives.pills.maxCredits", { n: shown });
      default:
        return "";
    }
  }

  function renderElectives() {
    if (!ui.electives) return;
    var data = runtime.electives;
    var show = !!(data && data.available);
    setHidden(ui.electives, !show);
    if (!show) return;

    // הערת השנתון על רשימת הבחירה. ‏``notes`` בלבד — ``warnings`` הוא יומן
    // החילוץ ("prereq ריק", "code: null") ואין לו מה לעשות על המסך.
    if (ui.electivesNotes) {
      var notes = pickList(data, ["notes"], null)
        .map(txt)
        .filter(Boolean);
      setText(ui.electivesNotes, notes.join(" "));
      setHidden(ui.electivesNotes, notes.length === 0);
    }

    // ‏רשימת החוקים אינה מוצגת (DESIGN.md, "Elective clusters"); נשאר רק
    // ‏ההסבר למה אין עדיין רשימות, בתוכנית שבה הן תלויות בהתמחות.
    setHidden(ui.electivesNeedsSpec, !data.needs_specialization);

    var picked = selectedSet();
    var notesByCluster = clusterNotes(data);
    var mandatory = specMandatoryCodes();
    var chipSpec = chosenSpecialization();

    // ‏חוקים מילוליים שהנתונים מסמנים ``show`` ואינם על רשימה: שורה אחת
    // ‏כל אחד, מתחת לכותרת.
    rebuild(ui.electivesHeadNotes, function (box) {
      (data.rules || []).forEach(function (rule) {
        if (!rule.show || (rule.lists || []).length || !txt(rule.text)) return;
        box.appendChild(el("p", { class: "elective-cluster-note", text: txt(rule.text) }));
      });
    });

    rebuild(ui.electivesGroups, function (box) {
      (data.clusters || []).forEach(function (cluster) {
        var head = el("div", { class: "elective-cluster-head" }, [
          el("h4", { class: "elective-cluster-title", text: txt(cluster.title) }),
        ]);
        // ‏✓ על "לפחות N קורסים" כשנבחרו N קורסים מהאשכול בסמסטר הזה. זה
        // ‏"נבחר עכשיו", לא "הושלם": מה שנלמד קודם אינו ידוע.
        var pickedCodes = (cluster.courses || [])
          .map(function (course) {
            return txt(course.code);
          })
          .filter(function (c) {
            return c && picked[c] === true;
          });
        (cluster.pills || []).forEach(function (pill) {
          var label = pillText(pill);
          if (!label) return;
          var counts =
            txt(pill.type) === "min_courses" || txt(pill.type) === "min_total_courses";
          // ‏``count_one_of``: מכל קבוצה כזו נספר קורס אחד (‏51535/51537).
          var hits = pickedCodes.slice();
          (pill.count_one_of || []).forEach(function (group) {
            var inGroup = hits.filter(function (c) {
              return group.indexOf(c) !== -1;
            });
            hits = hits.filter(function (c) {
              return inGroup.slice(1).indexOf(c) === -1;
            });
          });
          var node = el("span", { class: "pill elective-pill", text: label });
          if (counts && num(pill.n, 0) > 0 && hits.length >= num(pill.n, 0)) {
            node.classList.add("is-picked");
            node.appendChild(
              el("span", {
                class: "elective-pill-check",
                attrs: { title: T("app.electives.pickedHere"), "aria-label": T("app.electives.pickedHere") },
                text: "✓",
              })
            );
          }
          head.appendChild(node);
        });
        var chips = el("div", { class: "elective-chips" });
        (cluster.courses || []).forEach(function (course) {
          var code = txt(course.code);
          // שורה בלי מספר קורס אינה ניתנת לבחירה: אין מה לשלוח לשרת ואין
          // מה לשבץ. בשנתון המתמטיקה קורסי בחירה מודפסים כך ("חדש",
          // "מחליף"), והם **כן** קורסים — ולכן הם נאמרים ולא נמחקים.
          if (!code) {
            chips.appendChild(
              el("span", {
                class: "elective-chip is-static",
                attrs: { title: txt(course.note) || T("app.electives.noCode") },
                text: txt(course.name),
              })
            );
            return;
          }
          var chosen = picked[code] === true;
          chips.appendChild(
            el(
              "button",
              {
                class: "elective-chip" + (chosen ? " is-selected c" + colorOf(code) : ""),
                attrs: {
                  type: "button",
                  "aria-pressed": chosen ? "true" : "false",
                  title: course.credits !== null && course.credits !== undefined
                    ? Tf("app.courses.creditsUnit", { credits: fmtCredits(course.credits) })
                    : "",
                },
                data: { code: code },
                on: {
                  click: function () {
                    if (chosen) toggleCourse(code, false);
                    else addCourse(code, course.name, course.credits, { keepQuery: true });
                  },
                },
              },
              [
                el("span", { class: "course-code", text: code }),
                el("span", { class: "elective-chip-name", text: txt(course.name) }),
              ].concat(
                chipSpec && mandatory[code]
                  ? [el("span", { class: "tag tag--spec", text: Tf("app.courses.tags.specialization", { name: chipSpec }) })]
                  : []
              )
            )
          );
        });
        var parts = [head, chips];
        (notesByCluster[txt(cluster.key)] || []).forEach(function (line) {
          parts.push(el("p", { class: "elective-cluster-note", text: line }));
        });
        box.appendChild(el("section", { class: "elective-cluster", data: { key: txt(cluster.key) } }, parts));
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
    if (catalogBrowseBroken()) note += " " + T("app.catalog.browseUnavailable");
    setText(ui.browseNote, note);

    if (ui.browseList) {
      rebuild(ui.browseList, function (list) {
        if (runtime.browseError) {
          list.appendChild(
            el("p", {
              class: "note",
              text: Tf("app.catalog.browseFailed", { error: runtime.browseError }),
            })
          );
          return;
        }
        if (!runtime.browseResults.length) {
          list.appendChild(
            el("p", {
              class: "note",
              text: runtime.browseBusy
                ? T("app.catalog.loading")
                : runtime.browseQuery
                ? T("app.catalog.noResults")
                : T("app.catalog.empty"),
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
      bits.push(
        runtime.browseTotal !== null &&
          runtime.browseTotal > runtime.browseResults.length
          ? Tf("app.catalog.showingOfTotal", {
              count: runtime.browseResults.length,
              total: runtime.browseTotal,
            })
          : Tf("app.catalog.showing", { count: runtime.browseResults.length })
      );
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
  /**
   * מה יאפשר את יעד הימים — נמדד, ולא מנוחש.
   *
   * הכלל זהה למצב "אין פתרון": מספר מוצג רק אם פתירה אמיתית הפיקה אותו,
   * והשורה אומרת גם מה הוויתור **עולה** — בנקודות זכות. שני קורסים
   * שפותחים את אותו יעד אינם שקולים.
   */
  function renderDaysRelax(s) {
    if (!ui.daysRelax) return;
    var data = (s && s.day_relaxations) || {};
    var items = pickList(data, ["items"], null);
    var checked = pickList(data, ["checked"], null);
    var target = num(data.target, state.targetDays);
    var show = s && s.target_reachable === false && (items.length || checked.length);
    setHidden(ui.daysRelax, !show);
    if (!show) return;

    // ‏אין ויתור בודד שמגיע ליעד: שורה אחת, וזהו. לא כותרת, לא רשימת מה
    // שנבדק ולא הסתייגות על קורסי חובה — כשאין מה להציע אומרים את זה
    // (docs/DESIGN.md, עיקרון 5).
    var none = !items.length;
    setHidden(ui.daysRelaxTitle, none);
    setHidden(ui.daysRelaxList, none);
    setHidden(ui.daysRelaxNote, none);
    setHidden(ui.daysRelaxIntro, !none);
    setText(ui.daysRelaxTitle, none ? "" : Tf("app.days.relaxTitle", { days: target }));
    setText(ui.daysRelaxIntro, none ? Tf("app.days.relaxUnreachable", { days: target }) : "");
    if (none) {
      rebuild(ui.daysRelaxList, function () {});
      setText(ui.daysRelaxNote, "");
      return;
    }

    rebuild(ui.daysRelaxList, function (box) {
      items.forEach(function (item) {
        var names = (item.names || []).join(", ");
        var credits = num(item.credits, 0);
        var days = item.min_days;
        var text;
        if (item.codes && item.codes.length > 1) {
          text = Tf("app.days.relaxPackage", {
            names: names, credits: credits, days: days,
          });
        } else if (credits > 0) {
          text = Tf("app.days.relaxOption", {
            name: names, credits: credits, days: days,
          });
        } else {
          // נ"ז 0 בידיעון אינו "בחינם" — הוא פשוט לא ידוע. לא ממציאים מחיר.
          text = Tf("app.days.relaxOptionNoCredits", { name: names, days: days });
        }
        var li = el("li", { class: "days-relax-row" }, [
          el("span", { class: "days-relax-what", text: text }),
          item.schedules === null || item.schedules === undefined
            ? el("span", {
                class: "days-relax-count is-quiet",
                text: T("app.days.relaxUnmeasured"),
              })
            : el("span", {
                class: "days-relax-count",
                text: Tf("app.days.relaxSchedules", { n: item.schedules }),
              }),
        ]);
        box.appendChild(li);
      });
    });

    // הסתייגות, לא הערת שוליים: המערכת מציעה לוותר על קורסים בלי לדעת
    // אילו מהם חובה לתואר. עד שיהיה סימון כזה (ראי DEFERRED.md), עדיף
    // לומר את זה — פעם אחת, במשפט אחד — מאשר לתת לרשימה להישמע סמכותית
    // מכפי שהיא. מה שנבדק ולא הספיק כבר אינו מוצג.
    setText(ui.daysRelaxNote, T("app.days.relaxNoRequiredInfo"));
  }


  function renderDaysStep() {
    var s = runtime.solve || {};
    var minDays = num(s.min_days, null);

    ui.dayButtons.forEach(function (btn) {
      var n = num(btn.dataset.days, 0);
      btn.setAttribute(
        "aria-checked",
        num(state.targetDays, null) !== null && n === state.targetDays ? "true" : "false"
      );
      // יעד שנמוך מהמינימום האפשרי מסומן — אבל נשאר לחיץ, כי הוא רק העדפה.
      // ‏docs/DESIGN.md אמר "cannot be selected"; הוחלט (2026-09-24) להשאיר
      // אותו לחיץ, כי בחירתו היא הדרך היחידה אל "מה יאפשר N ימים".
      setClass(btn, "is-impossible", minDays !== null && n < minDays);
      // ‏המינימום נאמר על הכפתור עצמו, פעם אחת. אריח "מינימום אפשרי" והערת
      // ‏"המינימום האפשרי הוא N" שחזרו עליו הוסרו בשלב 3 של העיצוב.
      var tag = btn.querySelector(".day-min-tag");
      if (tag) tag.hidden = !(minDays !== null && n === minDays);
      btn.setAttribute(
        "title",
        minDays !== null && n < minDays
          ? Tf("app.days.targetImpossibleTitle", { days: n, min: minDays })
          : ""
      );
    });

    renderDaysRelax(s);
    setClass(ui.daysRow, "has-min", minDays !== null);
    renderAdvancedValues();

    if (ui.daysWarning) {
      if (s.target_reachable === false && minDays !== null) {
        setText(
          ui.daysWarning,
          txt(s.target_message) ||
            Tf("app.days.targetImpossible", {
              days: state.targetDays,
              min: minDays,
            })
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
          var label = Tf("app.days.blockedWindow", {
            day: dayLetter(day),
            from: fmtTime(win[1]),
            to: fmtTime(win[2]),
          });
          box.appendChild(
            el("button", {
              class: "tag",
              attrs: { type: "button", title: T("app.days.removeBlocked") },
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

  /**
   * ‏השורה שבכותרת "הגדרות נוספות": מה שונה מברירת המחדל, כדי שהגדרה פעילה
   * לא תסתתר מאחורי קיפול סגור. ריקה כשהכול בברירת מחדל. ‏CSS מציג אותה
   * רק כשהקיפול סגור — כשהוא פתוח הפקדים עצמם אומרים את זה.
   */
  function renderAdvancedValues() {
    if (!ui.advancedValues) return;
    var parts = [];
    if (state.forbidFriday === true) parts.push(T("app.days.extras.noFriday"));
    if (state.earliest !== null) {
      parts.push(Tf("app.days.extras.earliest", { time: fmtTime(state.earliest) }));
    }
    if (state.latest !== null) {
      parts.push(Tf("app.days.extras.latest", { time: fmtTime(state.latest) }));
    }
    var blocked = state.blocked.length;
    if (blocked === 1) parts.push(T("app.days.extras.blockedOne"));
    else if (blocked > 1) parts.push(Tf("app.days.extras.blockedMany", { n: blocked }));
    setText(ui.advancedValues, parts.join(" · "));
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
    if (i === -1) {
      list.push(name);
      // הדירוג שזה עתה ניתן — ‏groupRow מקפיץ את העיגול שלו, פעם אחת.
      runtime.popRank = { code: txt(code), lecturer: name, at: Date.now() };
    }
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
            el("p", { class: "note", text: T("app.lecturers.empty") })
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
              el("span", { class: "lect-course-title", text: T("app.lecturers.missing.title") }),
            ]),
            // השלב אינו חסום בגללם, ולכן הוא אומר את זה.
            el("p", { class: "note", text: T("app.lecturers.missing.note") }),
          ]);
          missing.forEach(function (rec) {
            var line = el("div", { class: "field-row" }, [
              el("span", {
                class: "note",
                text: Tf("app.lecturers.missing.line", {
                  code: rec.code,
                  name: rec.name || nameOf(rec.code),
                  reason: missingReason(rec, T("app.lecturers.missing.reasonDefault")),
                }),
              }),
            ]);
            // ‏כפתור רק כשיש מה ללחוץ עליו: שליפה מותרת בשרת הזה, **וגם**
            // השרת אמר שלקוד הזה חסרים נתונים שמשיכה עשויה להביא. בלי
            // שניהם זה כפתור שמבטיח משהו שלא יקרה.
            if (runtime.canFetch && rec.needs_scrape) {
              line.appendChild(retryButton(rec.code, T("app.lecturers.retry")));
            }
            warnBox.appendChild(line);
          });
          box.appendChild(warnBox);
        }

        var openCode = openCourseCode();
        state.codes.forEach(function (code) {
          var course = courseDataByCode(code);
          if (!course) {
            if (explained[txt(code)]) return;
            var st = courseStatus(code, true, false);
            var wrap = el("div", { class: "field-row" }, [
              el("span", {
                class: "note",
                text: Tf("app.lecturers.pending.line", {
                  code: code,
                  name: nameOf(code),
                  status: st.text || T("app.lecturers.pending.status"),
                }),
              }),
            ]);
            if (st.retry) wrap.appendChild(retryButton(code, T("app.lecturers.retry")));
            box.appendChild(wrap);
            return;
          }
          box.appendChild(coursePanel(course, txt(code) === openCode));
        });
      });
    }

    renderAttendanceNote();

    if (ui.lectNote) {
      var bits = [];
      if (rankedCount()) bits.push(Tf("app.lecturers.note.ranked", { count: rankedCount() }));
      if (pinCount()) bits.push(Tf("app.lecturers.note.pinned", { count: pinCount() }));
      setText(
        ui.lectNote,
        bits.length
          ? Tf("app.lecturers.note.summary", { bits: bits.join(" · ") })
          : T("app.lecturers.note.skip")
      );
    }
  }

  /**
   * ‏"N שיעורים ללא חובת נוכחות" — גלולה אחת שנפתחת לרשימה, ושורה אחת
   * שאומרת מה זה אומר (docs/DESIGN.md, Lecturers). כשאין כאלה — כלום.
   * ‏<details> כדי שהפתיחה תעבוד מהמקלדת בלי קוד; מצב הפתיחה נשמר ב-runtime
   * כי כל ציור בונה את הגלולה מחדש.
   */
  function renderAttendanceNote() {
    if (!ui.attendanceOff) return;
    var rows = [];
    runtime.courses.forEach(function (course) {
      var kinds = kindsOf(course);
      optionalKindsOf(course.code).forEach(function (kind) {
        if (kinds.indexOf(kind) === -1) return;
        rows.push(
          Tf("app.lecturers.attendance.offRow", {
            course: txt(course.name) || nameOf(course.code),
            kind: kind,
          })
        );
      });
    });
    setHidden(ui.attendanceOff, rows.length === 0);
    rebuild(ui.attendanceOff, function (box) {
      if (!rows.length) return;
      var list = el("ul", { class: "attendance-off-list" });
      rows.forEach(function (line) {
        list.appendChild(el("li", { text: line }));
      });
      var details = el("details", { class: "att-off" }, [
        el("summary", {
          class: "att-off-pill",
          data: { fk: "att-off" },
          text:
            rows.length === 1
              ? T("app.lecturers.attendance.offPillOne")
              : Tf("app.lecturers.attendance.offPill", { n: rows.length }),
        }),
        list,
      ]);
      details.open = runtime.attOffOpen === true;
      details.addEventListener("toggle", function () {
        runtime.attOffOpen = details.open;
      });
      box.appendChild(details);
      box.appendChild(
        el("p", { class: "note att-off-line", text: T("app.lecturers.attendance.offLine") })
      );
    });
  }

  /**
   * הקורס הפתוח באקורדיון. אחד בכל פעם; ‏"" = הכול סגור בבחירה מפורשת,
   * ‏null = עוד לא נבחר, ואז הראשון שיש לו נתונים פתוח.
   */
  function openCourseCode() {
    var codes = state.codes.map(txt).filter(function (code) {
      return !!courseDataByCode(code);
    });
    if (runtime.openCourse === "") return "";
    if (runtime.openCourse && codes.indexOf(runtime.openCourse) !== -1) {
      return runtime.openCourse;
    }
    return codes.length ? codes[0] : "";
  }

  /** הסיכום החי שבסוף כותרת הקורס: נעוץ, או סדר העדיפות, או "לא דורג". */
  function courseChoiceText(course) {
    var code = course.code;
    var pinned = [];
    kindsOf(course).forEach(function (kind) {
      var gid = pinnedGroup(code, kind);
      if (!gid) return;
      var group = course.groups.filter(function (g) {
        return txt(g.kind) === txt(kind) && txt(g.group_id) === txt(gid);
      })[0];
      var name = group && txt(group.lecturer)
        ? txt(group.lecturer)
        : T("app.lecturers.row.unknownLecturer");
      if (pinned.indexOf(name) === -1) pinned.push(name);
    });
    if (pinned.length) {
      return Tf("app.lecturers.choice.pinned", { list: pinned.join(" · ") });
    }
    var ranked = state.ranked[code] || [];
    if (ranked.length) {
      return Tf("app.lecturers.choice.ranked", { list: ranked.join(" ← ") });
    }
    return T("app.lecturers.choice.none");
  }

  /**
   * ההערות שהידיעון כותב על הקבוצות — בעיקר משפט חובת הנוכחות — פעם אחת
   * לקורס. עד שלב 4 של העיצוב הן חזרו מתחת למספר הקבוצה בכל שורה.
   */
  function courseNotes(course) {
    // ‏הידיעון מצרף כמה הערות לקבוצה אחת ב-" | ", ולכן "משפט הנוכחות" ו-
    // ‏"משפט הנוכחות | אין מועד קבוע" הן שתי הערות שונות שחוזרות על אותו
    // משפט. מפרקים לחלקים ומציגים כל חלק פעם אחת.
    var seen = [];
    (course.groups || []).forEach(function (g) {
      txt(g.note).split("|").forEach(function (part) {
        var note = part.trim();
        if (note && seen.indexOf(note) === -1) seen.push(note);
      });
    });
    return seen;
  }

  function coursePanel(course, open) {
    var code = course.code;
    var idx = colorOf(code);
    var bodyId = "lect-body-" + txt(code);

    // ‏פס צבע הקורס, שם, קוד ונ"ז, ובסוף מה נבחר. מספר הקבוצות, סדר
    // העדיפות המלא וגיל הנתונים ישבו כאן עד שלב 4: הראשון נראה בפתיחה,
    // השני בסיכום ובעיגולים, והשלישי נאמר פעם אחת — בכותרת העמוד.
    var head = el(
      "button",
      {
        class: "lect-course-head",
        attrs: {
          type: "button",
          "aria-expanded": open ? "true" : "false",
          "aria-controls": bodyId,
        },
        // ‏"lect-course-" ולא "course-": שלב 2 כבר משתמש ב-"course-<קוד>", ומפתח
        // משותף היה מחזיר את המיקוד לכרטיס הלא נכון אחרי ציור.
        data: { fk: "lect-course-" + code },
        on: {
          click: function () {
            runtime.openCourse = open ? "" : txt(code);
            render();
          },
        },
      },
      [
        el("span", { class: "lect-course-title", text: txt(course.name) || nameOf(code) }),
        el("span", {
          class: "lect-course-meta",
          text:
            txt(code) +
            " · " +
            Tf("app.lecturers.meta.credits", { credits: fmtCredits(creditsOf(code)) }),
        }),
        // הסיכום והחץ יחד, כדי שבמסך צר לא יישבר החץ לשורה משלו.
        el("span", { class: "lect-course-end" }, [
          el("span", { class: "lect-course-choice", text: courseChoiceText(course) }),
          el("span", { class: "lect-course-caret", attrs: { "aria-hidden": "true" } }),
        ]),
      ]
    );

    var body = el("div", { class: "lect-course-body", attrs: { id: bodyId } });
    body.hidden = !open;

    pickList(course, ["warnings"], null)
      .map(function (w) {
        return txt(typeof w === "object" ? w.text || w.message : w);
      })
      .filter(Boolean)
      .forEach(function (w) {
        body.appendChild(el("p", { class: "note", text: w }));
      });

    body.appendChild(attendanceBox(course));

    var table = el("table", { class: "lect-table" }, [
      el("thead", {}, [
        el("tr", {}, [
          el("th", { class: "th-rank", text: T("app.lecturers.table.rank") }),
          el("th", { text: T("app.lecturers.table.lecturer") }),
          el("th", { text: T("app.lecturers.table.kind") }),
          // יום ושעה בתא אחד: הם נקראים תמיד יחד, ושתי עמודות נפרדות
          // רק הרחיבו את הטבלה.
          el("th", { text: T("app.lecturers.table.when") }),
          el("th", { text: T("app.lecturers.table.room") }),
          el("th", {
            class: "th-pin",
            text: T("app.lecturers.table.pin"),
            attrs: { title: T("app.lecturers.pinHelp") },
          }),
        ]),
      ]),
    ]);
    var tbody = el("tbody");
    sortedGroups(course).forEach(function (group) {
      tbody.appendChild(groupRow(course, group));
    });
    table.appendChild(tbody);
    body.appendChild(el("div", { class: "lect-table-wrap" }, [table]));

    return el("section", { class: "lect-course c" + idx + (open ? " is-open" : "") }, [
      el("h3", { class: "lect-course-h" }, [head]),
      body,
    ]);
  }

  /**
   * מתג "חובת נוכחות" לכל סוג רכיב בקורס, ו-ⓘ אחד שפותח את ההסבר במקום.
   * ברירת המחדל דלוקה תמיד; כיבוי מרשה למנוע לשבץ את הרכיב במקביל לרכיב
   * אחר. ההסבר — מה המתג עושה, ולמה ברירת המחדל כאן היא מה שהיא — עבר
   * מאחורי ה-ⓘ; המשפט של הידיעון עצמו נשאר גלוי, פעם אחת.
   */
  function attendanceBox(course) {
    var code = course.code;
    var infoId = "att-info-" + txt(code);
    var infoOpen = runtime.attInfoOpen[txt(code)] === true;
    var box = el("div", { class: "lect-attendance" });
    var row = el("div", { class: "att-row" });
    var hints = [];

    kindsOf(course).forEach(function (kind) {
      var input = el("input", {
        attrs: { type: "checkbox", role: "switch" },
        data: { fk: "att-" + code + "-" + kind },
        on: {
          change: function (ev) {
            setAttendance(code, kind, ev.target.checked === true);
          },
        },
      });
      input.checked = attendanceRequired(code, kind);
      row.appendChild(
        el("label", { class: "att-switch" }, [
          input,
          el("span", { class: "att-switch-track", attrs: { "aria-hidden": "true" } }),
          el("span", { text: Tf("app.lecturers.attendance.label", { kind: kind }) }),
        ])
      );
      var note = attendanceNoteFor(course, kind);
      if (note) hints.push(Tf("app.lecturers.attendance.hint", { kind: kind, note: note }));
    });

    row.appendChild(
      el("button", {
        class: "info-btn",
        attrs: {
          type: "button",
          "aria-expanded": infoOpen ? "true" : "false",
          "aria-controls": infoId,
          "aria-label": T("app.lecturers.attendance.infoLabel"),
          title: T("app.lecturers.attendance.infoLabel"),
        },
        data: { fk: "att-info-" + code },
        text: "ⓘ",
        on: {
          click: function () {
            runtime.attInfoOpen[txt(code)] = !infoOpen;
            render();
          },
        },
      })
    );
    box.appendChild(row);

    courseNotes(course).forEach(function (note) {
      box.appendChild(el("p", { class: "note lect-course-note", text: note }));
    });

    var info = el("div", { class: "att-info", attrs: { id: infoId } });
    hints.forEach(function (hint) {
      info.appendChild(el("p", { text: hint }));
    });
    info.appendChild(el("p", { text: T("ui.lecturers.attendanceWhatBody") }));
    info.hidden = !infoOpen;
    box.appendChild(info);
    return box;
  }

  /** נעץ: מתאר כשהקבוצה פתוחה, מלא בצבע הקורס כשהיא נעוצה (‏CSS). */
  var PIN_SVG =
    '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
    '<path d="M9 3h6l-1.2 6.2L17 12.5V14h-4.2v6L12 21l-.8-1v-6H7v-1.5l3.2-3.3z"/>' +
    "</svg>";

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

    // ‏מספר הקבוצה אינו עמודה מאז שלב 4 של העיצוב — הוא הראשון ב-title של
    // השורה, ובשם הנגיש של כפתור הנעיצה.
    var title = [
      Tf("app.lecturers.row.groupTitle", { gid: gid }),
      dead
        ? txt(via.reason)
        : isPinned
        ? T("app.lecturers.row.pinnedTitle")
        : txt(group.lecturer)
        ? Tf(rank ? "app.lecturers.row.rankRemove" : "app.lecturers.row.rankAdd", {
            lecturer: group.lecturer,
          })
        : "",
    ]
      .filter(Boolean)
      .join(" · ");

    var tr = el("tr", {
      class: cls.replace(/^ /, ""),
      attrs: { title: title, "aria-disabled": dead ? "true" : null },
      data: { fk: "row-" + code + "-" + kind + "-" + gid },
      on: {
        click: function () {
          if (dead) return;
          toggleLecturer(code, group.lecturer);
        },
      },
    });

    // ‏עיגול הדירוג: ריק ומקווקו = "לחצו לדירוג", מלא וממוספר = הדירוג.
    // ‏הקפיצה רצה רק על הדירוג שזה עתה ניתן. ציור חוזר באמצע (הפתרון חוזר
    // מהשרת) בונה את העיגול מחדש, ולכן ההשהיה השלילית ממשיכה את האנימציה
    // מאיפה שהייתה במקום להתחיל אותה שוב.
    var circle = el("span", {
      class: "rank-circle" + (rank ? " is-ranked" : ""),
      attrs: { "aria-hidden": "true" },
      text: rank ? String(rank) : "",
    });
    var pop = runtime.popRank;
    if (rank && pop && pop.code === txt(code) && pop.lecturer === txt(group.lecturer)) {
      var age = Date.now() - pop.at;
      if (age < 250) {
        circle.classList.add("is-pop");
        circle.style.animationDelay = -age + "ms";
      }
    }
    tr.appendChild(el("td", { class: "cell-rank" }, [circle]));

    // מרצה, ומתחתיו מה שנאמר על השורה הזאת: הודעת הידיעון ("הקורס מלא")
    // ולמה אי אפשר לבחור בה.
    var lectCell = el("td", { class: "cell-lect" }, [
      el("span", { text: txt(group.lecturer) || T("app.lecturers.row.unknownLecturer") }),
    ]);
    if (group.linked_to && group.linked_to.length) {
      var linked = group.linked_to;
      var linkedLabel = Tf(
        linked.length === 1 ? "app.lecturers.row.linkedOne" : "app.lecturers.row.linkedMany",
        { list: linked.join(", ") }
      );
      lectCell.appendChild(
        el("span", {
          class: "link-badge",
          attrs: { title: linkedLabel, role: "img", "aria-label": linkedLabel },
          text: "🔗",
        })
      );
    }
    if (group.status_note) {
      lectCell.appendChild(el("div", { class: "row-sub group-status", text: group.status_note }));
    }
    if (dead) {
      lectCell.appendChild(el("div", { class: "row-sub row-dead", text: T("app.lecturers.row.deadLine") }));
    }
    tr.appendChild(lectCell);

    tr.appendChild(el("td", { text: kind }));

    // יום ושעה בתא אחד, וחדר לצידו — שורה לכל מפגש
    var whenCell = el("td");
    var roomCell = el("td");
    if (!group.meetings.length) {
      whenCell.appendChild(el("div", { text: T("app.lecturers.row.noMeetings") }));
      roomCell.appendChild(el("div", { text: "—" }));
    }
    group.meetings.forEach(function (m) {
      // התא עצמו נשאר ימין-לשמאל בגלל אות היום; רק טווח השעות מבודד
      // ל-LTR, אחרת "12:50–15:50" היה מתהפך לצד האות.
      whenCell.appendChild(
        el("div", { class: "when-line" }, [
          el("span", {
            class: "when-day",
            text: Tf("app.lecturers.dayCell", { day: dayLetter(m.day) }),
          }),
          el("span", { class: "cell-time", text: fmtTime(m.start) + "–" + fmtTime(m.end) }),
        ])
      );
      // ‏<bdi> סביב קוד החדר: "L 706", "EF 506 מע׳", "M 303" הם לטינית
      // בתוך עברית, וסדר התווים שלהם אינו יציב בלי בידוד מפורש.
      roomCell.appendChild(el("div", {}, [ltrCode(roomOf(m) || "—")]));
    });
    tr.appendChild(whenCell);
    tr.appendChild(roomCell);

    // נעיצה — כפתור נפרד; הלחיצה עליו לא מדרגת מרצה. ‏aria-label נושא את
    // המשמעות המלאה, כולל מספר הקבוצה.
    var pinLabel = dead
      ? Tf("app.lecturers.row.pinDead", { gid: gid, reason: txt(via.reason) })
      : Tf(isPinned ? "app.lecturers.row.pinRelease" : "app.lecturers.row.pinAdd", { gid: gid });
    var pinBtn = el("button", {
      class: "pin-btn",
      attrs: {
        type: "button",
        "aria-pressed": isPinned ? "true" : "false",
        "aria-label": pinLabel,
        title: pinLabel,
      },
      data: { fk: "pin-" + code + "-" + kind + "-" + gid },
      on: {
        click: function (ev) {
          ev.stopPropagation();
          if (dead) return;
          togglePin(code, kind, gid);
        },
      },
    });
    pinBtn.innerHTML = PIN_SVG;
    pinBtn.disabled = dead;
    tr.appendChild(el("td", { class: "cell-pin" }, [pinBtn]));

    return tr;
  }

  /**
   * טבלת "מה ההבדל?" — חמש המערכות מול העובדות שמשוות ביניהן.
   *
   * שני כללים שבלעדיהם הטבלה חסרת ערך:
   *   1. **לכל תא יש ערך.** צביעה בלבד אומרת "כאן שונה" בלי לומר במה,
   *      וטבלה של גוונים אינה עוזרת לבחור.
   *   2. שורה שכל ערכיה זהים מעומעמת, ושורה שנבדלת מודגשת — כדי שהעין
   *      תלך ישר למקום היחיד שבו ההחלטה נמצאת.
   * וכשאין שום הבדל, נאמר זאת במפורש במקום להציג חמש שורות זהות.
   */
  function renderCompare() {
    if (!ui.compareBody) return;
    var list = schedules();
    setHidden(ui.compare, list.length < 2);
    if (list.length < 2) return;

    var facts = list.map(scheduleFacts);
    var fits = fitScores(list);
    var labels = differentiators(list);

    var rows = [
      {
        key: "label",
        title: T("app.compare.rowLabel"),
        cell: function (i) {
          return labels[i];
        },
      },
      {
        key: "fit",
        title: T("app.compare.rowFit"),
        cell: function (i) {
          return fmtFit(fits[i]);
        },
      },
      {
        key: "days",
        title: T("app.compare.rowDays"),
        cell: function (i) {
          return String(facts[i].days);
        },
      },
      {
        key: "finish",
        title: T("app.compare.rowFinish"),
        cell: function (i) {
          return facts[i].finish ? fmtTime(facts[i].finish) : "—";
        },
      },
      {
        key: "gaps",
        title: T("app.compare.rowGaps"),
        cell: function (i) {
          return fmtDuration(facts[i].gaps);
        },
      },
      {
        key: "credits",
        title: T("app.compare.rowCredits"),
        cell: function (i) {
          return fmtNumber(facts[i].credits);
        },
      },
      {
        key: "lecturers",
        title: T("app.compare.rowLecturers"),
        cell: function (i) {
          return facts[i].lecturerTotal
            ? Tf("app.compare.lecturersCell", {
                hits: facts[i].lecturers,
                total: facts[i].lecturerTotal,
              })
            : "—";
        },
      },
    ];

    rows.forEach(function (row) {
      var values = list.map(function (_, i) {
        return row.cell(i);
      });
      row.values = values;
      row.varies = uniq(values).length > 1;
    });

    var anyVaries = rows.some(function (row) {
      return row.key !== "label" && row.varies;
    });

    rebuild(ui.compareBody, function (box) {
      if (!anyVaries) {
        box.appendChild(
          el("p", { class: "note", text: T("app.compare.allSame") })
        );
      }
      var table = el("table", {
        class: "compare-table",
        attrs: { "aria-label": T("app.compare.tableLabel") },
      });
      var head = el("tr", {}, [
        el("th", { attrs: { scope: "col" }, text: T("app.compare.rowSchedule") }),
      ]);
      list.forEach(function (_, i) {
        head.appendChild(
          el("th", {
            class: i === state.activeSchedule ? "is-active" : "",
            attrs: { scope: "col" },
            text: String(i + 1),
          })
        );
      });
      table.appendChild(el("thead", {}, [head]));

      var body = el("tbody");
      rows.forEach(function (row) {
        var tr = el("tr", { class: row.varies ? "varies" : "same" }, [
          el("th", {
            attrs: {
              scope: "row",
              title: row.varies
                ? T("app.compare.differs")
                : T("app.compare.same"),
            },
            text: row.title,
          }),
        ]);
        row.values.forEach(function (value, i) {
          tr.appendChild(
            el("td", {
              class:
                (i === state.activeSchedule ? "is-active " : "") +
                (row.varies ? "is-diff" : "is-same"),
              text: value,
            })
          );
        });
        body.appendChild(tr);
      });
      table.appendChild(body);
      box.appendChild(el("div", { class: "compare-scroll" }, [table]));
    });
  }

  /* --- שלב 4: פרטי שיעור ------------------------------------------- */

  /**
   * פותח את פאנל הפרטים של שיעור (או של שני צדדיה של חפיפה מכוונת).
   *
   * מרגע שהבלוק ברשת מציג שם, שעה וסוג בלבד, זה המקום **היחיד** שבו
   * מופיעים מספר הקבוצה, המרצה והחדר. לכן:
   *   * הבלוקים הם ``<button>`` — יש אליהם דרך במקלדת, לא רק בעכבר.
   *   * הפוקוס עובר לפאנל בפתיחה. קורא מסך מכריז אז את שם הדיאלוג
   *     ותוכנו; בלי זה הפאנל היה נפתח בשקט ומי שאינו רואה אותו לא היה
   *     יודע שקרה משהו.
   *   * ‏Esc סוגר, והפוקוס חוזר לבלוק שממנו נפתח.
   */
  function openMeetingDetail(group, isOverlap) {
    if (!ui.detail || !ui.detailBody) return;
    runtime.detailReturnTo = document.activeElement;
    rebuild(ui.detailBody, function (box) {
      if (isOverlap) {
        box.appendChild(
          el("p", { class: "detail-overlap" }, [
            el("strong", { text: T("app.detail.overlapTitle") }),
            el("span", { text: " " + T("app.detail.overlapNote") }),
          ])
        );
      }
      group.forEach(function (m) {
        var rows = [
          [T("app.detail.course"), txt(m.name) || nameOf(m.code), m.code, false],
          [T("app.detail.kind"), txt(m.kind), "", false],
          [T("app.detail.group"), txt(m.group_id), "", true],
          [
            T("app.detail.lecturer"),
            txt(m.lecturer) || T("app.detail.unknownLecturer"),
            "",
            false,
          ],
          [T("app.detail.room"), roomOf(m) || T("app.detail.noRoom"), "", true],
          [
            T("app.detail.when"),
            Tf("app.detail.whenValue", {
              day: dayLetter(m.day),
              from: fmtTime(m.start),
              to: fmtTime(m.end),
            }),
            "",
          ],
        ];
        var dl = el("dl", { class: "detail-list" });
        rows.forEach(function (row) {
          dl.appendChild(el("dt", { text: row[0] }));
          // ‏<bdi> סביב כל מזהה לטיני בתוך עברית — "L 706", "EF 506 מע׳",
          // "271060310/1". בלי בידוד הם מסתדרים מחדש בצורה בלתי צפויה.
          var dd = el("dd", {}, [
            row[3] ? ltrCode(row[1]) : el("span", { text: row[1] }),
          ]);
          if (row[2]) {
            var code = ltrCode(row[2]);
            setClass(code, "detail-code", true);
            dd.appendChild(code);
          }
          dl.appendChild(dd);
        });
        box.appendChild(
          el("section", { class: "detail-item c" + colorOf(m.code) }, [dl])
        );
      });
    });
    setHidden(ui.detail, false);
    try {
      ui.detail.focus();
    } catch (e) {
      /* פוקוס נכשל — הפאנל עדיין פתוח */
    }
  }

  function closeMeetingDetail() {
    if (!ui.detail) return;
    setHidden(ui.detail, true);
    var back = runtime.detailReturnTo;
    runtime.detailReturnTo = null;
    if (back && back.isConnected && back.offsetParent !== null) {
      try {
        back.focus();
      } catch (e) {
        /* לא נורא */
      }
    }
  }

  /* --- שלב 3: מה מבדיל בין המערכות ---------------------------------- */

  /**
   * העובדות שמשוות ביניהן. כל מה שאחריו נגזר מכאן, כדי שהטבלה, התוויות
   * וההחלטה "האם יש בכלל הבדל" יסתמכו על אותה רשימה בדיוק.
   */
  function scheduleFacts(sch) {
    var finish = lastFinishOf(sch);
    var credits = scheduleCredits(sch);
    return {
      days: num(sch && sch.days_count, 0),
      finish: finish === null ? 0 : finish,
      gaps: num(sch && sch.gap_minutes, 0),
      credits: num(credits && credits.total, 0),
      lecturers: num(sch && sch.lecturer_hits, 0),
      lecturerTotal: num(sch && sch.lecturer_total, 0),
    };
  }

  /** ‏{"61756|תרגול": "271060310/1", …} — הקבוצות שנבחרו בפועל. */
  function schedulePicks(sch) {
    var map = Object.create(null);
    pickList(sch, ["picks"], null).forEach(function (p) {
      map[txt(p.code) + "|" + txt(p.kind)] = txt(p.group_id);
    });
    return map;
  }

  /** באילו רכיבים שתי מערכות בחרו קבוצה אחרת. */
  function pickDiff(a, b) {
    var pa = schedulePicks(a);
    var pb = schedulePicks(b);
    var keys = uniq(Object.keys(pa).concat(Object.keys(pb)));
    return keys
      .filter(function (k) {
        return pa[k] !== pb[k];
      })
      .map(function (k) {
        return { code: k.split("|")[0], kind: k.split("|")[1] || "" };
      });
  }

  /**
   * תווית שמבדילה כל מערכת מהאחרות — **נגזרת ממה שבאמת שונה**, ולא
   * מרשימה קבועה.
   *
   * הסדר: קודם מחפשים עובדה שבה המערכת הזאת טובה מכולן ויחידה בכך. אם
   * אין — ואם מספר הימים בכלל משתנה בין המערכות — אומרים כמה ימים היא.
   * ואם היא זהה לגמרי לאחרת בכל העובדות, זה מה שנאמר, יחד עם מה שכן
   * שונה ביניהן (קבוצת תרגול אחת, למשל). להמציא הבדל שאינו קיים גרוע
   * מלהודות שאין.
   */
  function differentiators(list) {
    var facts = list.map(scheduleFacts);
    var fits = fitScores(list);

    function uniqueBest(key, better) {
      var best = null;
      facts.forEach(function (f) {
        if (best === null || better(f[key], best)) best = f[key];
      });
      var holders = [];
      facts.forEach(function (f, i) {
        if (f[key] === best) holders.push(i);
      });
      return holders.length === 1 ? holders[0] : -1;
    }

    var lower = function (v, best) {
      return v < best;
    };
    var higher = function (v, best) {
      return v > best;
    };

    var labels = list.map(function () {
      return "";
    });
    var claim = function (idx, text) {
      if (idx >= 0 && !labels[idx]) labels[idx] = text;
    };

    // כל המרצים המועדפים — החזק ביותר, כי הוא בקשה מפורשת של הסטודנט/ית.
    facts.forEach(function (f, i) {
      if (f.lecturerTotal > 0 && f.lecturers === f.lecturerTotal) {
        var others = facts.filter(function (g, j) {
          return j !== i && g.lecturers === g.lecturerTotal;
        });
        if (!others.length) claim(i, T("app.compare.allLecturers"));
      }
    });
    claim(uniqueBest("lecturers", higher), T("app.compare.mostLecturers"));
    claim(uniqueBest("days", lower), T("app.compare.bestDays"));
    claim(uniqueBest("finish", lower), T("app.compare.bestFinish"));
    claim(uniqueBest("gaps", lower), T("app.compare.bestGaps"));

    // ‏**קודם** התאומות. מערכת שזהה לקודמת בכל העובדות אינה "4 ימי
    // לימוד" — זו תווית שגם הקודמת נושאת, ושתי לשוניות עם אותו טקסט הן
    // בדיוק חוסר ההבחנה שהשלב הזה בא לתקן. אומרים שהיא דומה, ומה כן שונה.
    facts.forEach(function (f, i) {
      if (labels[i]) return;
      var twin = -1;
      for (var j = 0; j < i; j++) {
        if (sameFacts(facts[j], f)) {
          twin = j;
          break;
        }
      }
      if (twin === -1) return;
      var diff = pickDiff(list[twin], list[i]);
      if (!diff.length) {
        labels[i] = Tf("app.compare.identical", { n: twin + 1 });
      } else if (diff.length === 1) {
        labels[i] = Tf("app.compare.sameAs", {
          n: twin + 1,
          kind: diff[0].kind || T("app.compare.rowSchedule"),
        });
      } else {
        labels[i] = Tf("app.compare.sameAsMany", {
          n: twin + 1,
          count: diff.length,
        });
      }
    });

    // ומה שנשאר: אם מספר הימים בכלל משתנה בין המערכות, הוא ההבדל
    // הקריא ביותר. אחרת — ההתאמה הגבוהה ביותר, או מספר הימים כגיבוי.
    var daysVary =
      uniq(
        facts.map(function (f) {
          return f.days;
        })
      ).length > 1;
    var bestFit = fits.length ? Math.max.apply(null, fits) : 0;
    facts.forEach(function (f, i) {
      if (labels[i]) return;
      if (daysVary) {
        labels[i] = Tf("app.compare.daysLabel", { days: f.days });
      } else if (fits[i] === bestFit) {
        labels[i] = T("app.compare.bestOverall");
      } else {
        labels[i] = Tf("app.compare.daysLabel", { days: f.days });
      }
    });
    return labels;
  }

  function sameFacts(a, b) {
    return (
      a.days === b.days &&
      a.finish === b.finish &&
      a.gaps === b.gaps &&
      a.credits === b.credits &&
      a.lecturers === b.lecturers
    );
  }

  /* --- שלב 5: התאמה, קנסות ומרצים -------------------------------- */

  /**
   * ‏0..100 ביחס לחמש המערכות המוצגות בלבד, כשהטובה מביניהן היא 100.
   *
   * זה ציון **יחסי** ולא מוחלט, ואי אפשר שיהיה אחרת: ``lecturer`` הוא בונוס
   * ללא תקרה ידועה וכל השאר קנסות, כך שאין ציון מרבי לנרמל אליו. לכן גם
   * התיאור אומר במפורש "ביחס לחמש המוצגות", והניקוד הגולמי נשאר זמין
   * במצב ניפוי.
   *
   * כשכל המערכות שקולות — וזה המצב הרגיל כשהן נבדלות בקבוצת תרגול אחת —
   * כולן מקבלות 100, במקום לפרוש הפרש של נקודה על פני 0..100 ולהמציא
   * הבדל שאינו קיים.
   */
  function fitScores(list) {
    var scores = list.map(function (sch) {
      return num(sch && sch.score, 0);
    });
    if (!scores.length) return [];
    var best = Math.max.apply(null, scores);

    // הפער נמדד ביחס ל**גודל** הניקוד של הטובה, ולא ביחס לטווח שבין
    // הטובה לגרועה. מתיחה על פני הטווח נשמעת נכונה עד שמסתכלים במספרים:
    // חמש מערכות בטווח ‎-75.3..-83.2‎ — הפרש של כ-10% — היו נפרשות ל-
    // ‎100, 100, 5, 5, 1‎, כלומר מערכת סבירה לגמרי הייתה נקראת "1 מתוך 100".
    // כאן אותן חמש יוצאות ‎100, 100, 90, 90, 90‎: דומות, וזו האמת.
    var scale = Math.max(Math.abs(best), 1);
    return scores.map(function (v) {
      return clamp(Math.round(100 * (1 - (best - v) / scale)), 0, 100);
    });
  }

  /** רק המרכיבים ששוללים נקודות, מהמשפיע ביותר ומטה. */
  function penaltyList(sch) {
    var breakdown = (sch && sch.breakdown) || {};
    var rows = [];
    Object.keys(breakdown).forEach(function (key) {
      var value = num(breakdown[key], 0);
      if (value >= 0) return; // בונוס אינו קנס
      rows.push({ key: key, value: value, size: Math.abs(value) });
    });
    rows.sort(function (a, b) {
      return b.size - a.size;
    });
    return rows;
  }

  /**
   * מרצים שדורגו ולא נכנסו למערכת הזו.
   * ‏lecturer_hits/total מגיעים מהשרת ואומרים כמה — לא מי. השם הוא מה
   * שמאפשר להחליט אם כדאי לוותר, ולכן הוא נגזר כאן מהבחירה בפועל.
   */
  function missingLecturers(sch) {
    if (!sch) return [];
    var chosen = Object.create(null);
    scheduleMeetings(sch).forEach(function (m) {
      var name = txt(m.lecturer);
      if (name) chosen[txt(m.code) + "|" + name] = true;
    });
    var missing = [];
    Object.keys(state.ranked || {}).forEach(function (code) {
      var names = state.ranked[code] || [];
      if (!names.length) return;
      var got = names.some(function (name) {
        return chosen[code + "|" + txt(name)];
      });
      if (!got) missing.push(txt(names[0]));
    });
    return uniq(missing.filter(Boolean));
  }

  /* --- שלב 5: המערכת ------------------------------------------------- */

  function renderScheduleStep() {
    var s = runtime.solve;
    var list = schedules();
    var feasible = s ? num(s.feasible_count, list.length) : null;
    var infeasible = !!s && list.length === 0;

    // אותן תוויות משמשות את הלשוניות ואת שורת הכותרת של ההדפסה:
    // הנייר צריך לומר איזו מערכת זו באותן מילים שבהן היא נבחרה.
    var tabLabels = differentiators(list);

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
              // מה שמבדיל אותה, ולא "5 ימים · זמן המתנה 3:00" שחוזר זהה
              // בכל לשונית ולכן אינו עוזר לבחור.
              text: Tf("app.schedule.tabLabel", {
                n: idx + 1,
                label: tabLabels[idx],
              }),
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

    // ‏שבבי הנתונים, ומתחתם מה הוריד מההתאמה (DESIGN.md, "Results page", 4).
    if (ui.summary) {
      rebuild(ui.summary, function (box) {
        if (sch) buildStats(box, sch, list);
      });
    }

    // ‏המקרא, ומתחתיו קורס שאין לו מועד קבוע. לקורס כזה אין בלוק ברשת,
    // ולכן אין לו מקום במקרא — שבב בצבע שאינו צובע דבר — והוא נאמר בשורה
    // משלו מתחת (DESIGN.md, "Results page", 5).
    var unscheduled = sch ? unscheduledCourses(sch) : [];
    if (ui.legend) {
      rebuild(ui.legend, function (box) {
        buildLegend(box, sch, {
          skip: unscheduled.map(function (u) {
            return u.code;
          }),
        });
      });
    }
    if (ui.unscheduled) {
      setText(ui.unscheduled, unscheduled.length ? unscheduledLine(unscheduled) : "");
      setHidden(ui.unscheduled, !unscheduled.length);
    }

    // הרשת
    if (ui.grid) {
      rebuild(ui.grid, function (box) {
        if (!sch) return;
        buildGrid(box, sch, soft);
      });
    }
    setHidden(ui.gridScroll, !sch);
    // ‏גובה השעה נמדד אחרי הפריסה, לא כאן. ראו sizeGrid().
    requestGridSizing();

    // שורת הכותרת של הדף המודפס. מוסתרת על המסך, ולכן היא נבנית תמיד
    // ואינה תלויה במצב כלשהו — הדפסה יכולה להתחיל בכל רגע.
    if (ui.printHead) {
      var idx = num(state.activeSchedule, 0);
      ui.printHead.textContent = sch
        ? Tf("app.grid.printHead", {
            name: Tf("app.schedule.tabLabel", {
              n: idx + 1,
              label: tabLabels[idx] || "",
            }),
            date: todayLabel(),
          })
        : "";
    }

    // אין פתרון
    if (ui.empty) {
      setHidden(ui.empty, !infeasible);
      if (infeasible) {
        if (ui.reasons) {
          rebuild(ui.reasons, function (box) {
            var reasons = pickList(s, ["reasons"], null);
            if (!reasons.length) {
              box.appendChild(
                el("li", { text: T("app.schedule.noReasons") })
              );
            }
            // הסיבות מסבירות את העבר; שורות הוויתור הן מה שעושים.
            // לכן הראשונה גלויה והשאר מתקפלות — ולא להפך.
            var texts = reasons.map(function (r) {
              return txt(typeof r === "object" ? r.text || r.reason : r);
            });
            if (texts.length) box.appendChild(el("li", { text: texts[0] }));
            if (texts.length > 1) {
              var rest = texts.slice(1);
              var more = el("details", { class: "reasons-more" }, [
                el("summary", {
                  text:
                    rest.length === 1
                      ? T("app.schedule.moreReasonsOne")
                      : Tf("app.schedule.moreReasons", { n: rest.length }),
                }),
                el(
                  "ul",
                  { class: "reasons" },
                  rest.map(function (t) {
                    return el("li", { text: t });
                  })
                ),
              ]);
              box.appendChild(el("li", { class: "reasons-more-wrap" }, [more]));
            }
          });
        }
        renderRelaxations(s);
        renderRelaxUndo();
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
                    text: T("app.schedule.unpinAll"),
                    on: {
                      click: function () {
                        setState({ pinned: {}, activeSchedule: 0 });
                        toast(T("app.schedule.unpinAllToast"), "ok");
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
        note = T("app.schedule.noteNoCourses");
      } else if (runtime.solveBusy && !s) {
        note = T("app.schedule.noteSolving");
      } else if (runtime.solveError) {
        note = Tf("app.schedule.noteFailed", { error: runtime.solveError });
      } else if (s && !infeasible) {
        // כמה מערכות נמצאו בסך הכול וכמה זמן לקח החישוב הם פירוט טכני.
        note = Tf("app.schedule.noteShown", { shown: list.length });
      }
      // חישוב שרץ מקבל כפתור עצירה לידו. מסך שאי אפשר לצאת ממנו הוא
      // מסך נעול, גם אם ההמתנה קצרה ברוב המקרים.
      rebuild(ui.scheduleNote, function (box) {
        if (note) box.appendChild(el("span", { class: "note-text", text: note }));
        if (runtime.solveBusy) {
          box.appendChild(
            el("button", {
              class: "btn btn-ghost btn-sm",
              attrs: {
                type: "button",
                title: T("app.schedule.solvingCancelTitle"),
              },
              data: { fk: "solve-cancel" },
              text: T("app.schedule.solvingCancel"),
              on: { click: cancelSolve },
            })
          );
        } else if (runtime.solveError) {
          // שגיאה מגיעה עם דרך החוצה, לא רק עם תיאור.
          box.appendChild(
            el("button", {
              class: "btn btn-outline btn-sm",
              attrs: { type: "button" },
              data: { fk: "solve-retry" },
              text: T("app.errors.retry"),
              on: {
                click: function () {
                  runtime.solveError = null;
                  scheduleSolve(0);
                },
              },
            })
          );
        }
      });
    }
  }

  /**
   * שבבי הנתונים של המערכת שנבחרה, ומתחתם שורה אחת: מה הוריד מההתאמה.
   *
   * ‏DESIGN.md, "Results page", פריט 4 (2026-09-30). הם מחליפים שלושה
   * דברים — כותרת ההתאמה, פאנל העובדות ופסי הקנסות — וכל מה שהשלושה אמרו
   * נשאר: ההתאמה, הימים ואותיותיהם, שעת הסיום, זמן ההמתנה, הנ"ז (כולל
   * קורסים בלי נתון), כל קנס ומה שהוא מודד, מי מהמרצים המועדפים חסר, וכמה
   * מהם נכנסו. רק משפט ההסבר שליד ההתאמה ("ביחס לחמש המוצגות", "כולן
   * שקולות") עובר לתווית ההצפה של השבב.
   *
   * ‏הסדר קבוע: התאמה, ימים, סיום, חלונות, נ"ז — ואחריהם, כשיש העדפות
   * מרצים, כמה מהם נכנסו.
   */
  function buildStats(box, sch, list) {
    var fits = fitScores(list);
    var idx = clamp(state.activeSchedule, 0, Math.max(0, list.length - 1));
    var fit = fits.length ? fits[idx] : 100;
    var allTied = fits.length > 1 && fits.every(function (v) {
      return v === fits[0];
    });
    var bestFit = fits.length ? Math.max.apply(null, fits) : 0;
    // ‏המערכת המדורגת ראשונה מקבלת תווית במקום "100%". הרף נקבע על ידה —
    // ‏fitScores() נותן 100 לטובה מבין המוצגות — ולכן המספר שם נשמע מוחלט
    // הרבה יותר ממה שהוא. כשכולן שקולות אין "ראשונה", והמספר נשאר.
    var isBest = fits.length > 0 && !allTied && fit === bestFit;
    var missing = num(sch.lecturer_total, 0) > 0 ? missingLecturers(sch) : [];
    var hits = Tf("app.schedule.lecturersHits", {
      hits: num(sch.lecturer_hits, 0),
      total: num(sch.lecturer_total, 0),
    });

    var pills = el("div", {
      class: "stat-pills",
      attrs: { role: "list", "aria-label": T("app.schedule.statsLabel") },
    });
    var add = function (key, kids, title) {
      pills.appendChild(
        el(
          "span",
          {
            class: "stat-pill" + (key === "fit" ? " fit" : ""),
            attrs: { role: "listitem", title: title },
            data: { stat: key },
          },
          kids
        )
      );
    };

    // ‏1. ההתאמה. ‏"התאמה" אומר מה המספר מודד; ליד התווית של המובילה הוא
    // היה נקרא "התאמה · ההתאמה הגבוהה ביותר", ולכן הוא יורד שם. ‏class="ltr"
    // רק על המספר — על משפט עברי הוא היה כופה כיוון שגוי.
    var fitTitle = allTied ? T("app.schedule.fitTied") : T("app.schedule.fitTitle");
    add(
      "fit",
      isBest
        ? [el("strong", { class: "fit-value fit-value--best", text: T("app.compare.bestOverall") })]
        : [
            el("span", { class: "fit-label", text: T("app.schedule.fitLabel") }),
            el("strong", { class: "fit-value ltr", text: fmtFit(fit) }),
            DEBUG
              ? el("span", {
                  class: "fit-note ltr",
                  text: Tf("app.schedule.rawScore", { score: fmtNumber(sch.score) }),
                })
              : null,
          ],
      fitTitle
    );

    // ‏2. ימים, עם האותיות — "4 ימים" לבד אינו אומר אם יום ו׳ פנוי.
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
    var dayCount = num(sch.days_count, days.length);
    if (dayCount > 0) {
      var letters = days.map(dayLetter).join(" ");
      add("days", [
        el("span", {
          text: dayCount === 1
            ? Tf("app.schedule.pillDaysOne", { letters: letters })
            : Tf("app.schedule.pillDays", { n: dayCount, letters: letters }),
        }),
      ]);
    }

    // 3. שעת הסיום.
    var finish = lastFinishOf(sch);
    if (finish !== null) {
      add("finish", [
        el("span", { text: Tf("app.schedule.pillFinish", { time: fmtTime(finish) }) }),
      ]);
    }

    // 4. החלונות — ובלי חלונות, זה מה שנאמר, ולא "0:00 שעות".
    var gaps = Math.round(num(sch.gap_minutes, 0));
    add("gaps", [
      el("span", {
        text: gaps > 0
          ? Tf("app.schedule.pillGaps", { duration: fmtDuration(gaps) })
          : T("app.schedule.pillNoGaps"),
      }),
    ]);

    // ‏5. נ"ז — כולל כמה קורסים בלי נתון, כמו בכל סכום אחר באתר.
    add("credits", [
      el("span", { text: creditsText(scheduleCredits(sch), { unit: true, short: true }) }),
    ]);
    // ‏6. כמה מהמרצים המועדפים נכנסו — רק כשיש העדפות, ותמיד גלוי: בטלפון
    // אין תווית הצפה, ו-"3 מתוך 3" הוא מידע גם כששום דבר לא חסר.
    if (num(sch.lecturer_total, 0) > 0) add("lecturers", [el("span", { text: hits })]);
    box.appendChild(pills);

    // ---- מה הוריד מההתאמה: שורה אחת, מהמשפיע ביותר ומטה ----
    // ‏רכיב שמוצג כאפס בכל החלופות אינו אומר דבר, ולכן הוא לא נמנה. הסדר
    // הוא סדר ההשפעה; מה שכל רכיב מודד, ומי מהם הגדול, בתווית ההצפה.
    var items = penaltyList(sch)
      .filter(function (row) {
        return !breakdownAlwaysZero(list, row.key);
      })
      .map(function (row, i) {
        var label = T("app.score.breakdown." + row.key, row.key);
        var explain = T("app.score.explain." + row.key, "");
        return {
          key: row.key,
          text: label,
          title: i === 0
            ? Tf("app.schedule.topPenalty", { label: label }) + (explain ? "\n" + explain : "")
            : explain,
        };
      });
    // ‏המרצים המועדפים שלא נכנסו, בשמם: לפי השם מחליטים אם לוותר.
    if (missing.length) {
      items.push({
        key: "lecturer",
        text: Tf("app.schedule.missingLecturers", { names: missing.join(", ") }),
        title: T("app.score.explain.lecturer", ""),
      });
    }
    if (!items.length) return;

    // ‏הנוסח נשמר שלם ב-JSON, ו-{list} מוחלף כאן ברשימה שכל פריט בה נושא
    // את ההסבר שלו — אותה טכניקה כמו {author} בשורת התחתית.
    var parts = String(T("app.schedule.penaltiesLine")).split("{list}");
    var line = el("p", { class: "fit-lost" });
    line.appendChild(document.createTextNode(parts[0] || ""));
    items.forEach(function (item, i) {
      if (i) line.appendChild(document.createTextNode(", "));
      line.appendChild(
        el("span", {
          class: "fit-lost-item",
          attrs: { title: item.title },
          data: { penalty: item.key },
          text: item.text,
        })
      );
    });
    line.appendChild(document.createTextNode(parts[1] || ""));
    box.appendChild(line);
  }

  /**
   * שורת ההגדרות מעל התוצאה (DESIGN.md, "Results page", פריט 1): שבב לכל
   * שלב, באותו טקסט שהשלב מציג כשהוא מקופל — מקור אחד, ולא ניסוח שני —
   * ובסופה "עריכת ההגדרות", שמחזירה אל השלבים.
   *
   * ‏בפריסה הרחבה השורה תוסתר (שלב 7): שם השלבים עצמם על המסך.
   */
  function renderSettingsPills(steps, show) {
    if (!ui.settingsPills) return;
    setHidden(ui.settingsPills, !show);
    rebuild(ui.settingsPills, function (box) {
      if (!show) return;
      steps.forEach(function (step) {
        if (step.key === "schedule" || !step.text) return;
        // ‏סיכום שלב 1 הוא שנה וסמסטר בלבד — המסלול כתוב בתיבה שמעליו. כאן
        // אין תיבה, ולכן המסלול נכנס לשבב (DESIGN.md: "program, courses…").
        var text = step.key === "year" && identityChosen() && txt(state.program)
          ? Tf("app.schedule.settingsProgram", { program: txt(state.program), summary: step.text })
          : step.text;
        box.appendChild(
          el("span", { class: "settings-pill", data: { step: step.key }, text: text })
        );
      });
      box.appendChild(
        el("button", {
          class: "settings-edit",
          attrs: { type: "button" },
          data: { fk: "settings-edit" },
          text: T("app.schedule.settingsEdit"),
          on: { click: returnToSteps },
        })
      );
    });
  }

  /** "עריכת ההגדרות": חזרה אל השלב הראשון, כמו שכפתור הבנייה לוקח אל התוצאה. */
  function returnToSteps() {
    var first = ui.steps && ui.steps.year;
    if (!first) return;
    if (first.scrollIntoView) first.scrollIntoView({ block: "start" });
    var toggle = ui.stepToggles && ui.stepToggles.year;
    if (toggle && toggle.focus) {
      try {
        toggle.focus({ preventScroll: true });
      } catch (e) {
        toggle.focus();
      }
    }
  }

  /**
   * קורסים שאין להם אף מפגש במערכת הזו — פרויקט גמר, סמינר בתיאום, שו"ת
   * בלי מועד. לכל אחד: שם, סוגי השיעור ונ"ז.
   *
   * ‏קורס שחלק מרכיביו משובצים אינו כאן: יש לו בלוקים, ולכן גם מקום במקרא.
   */
  function unscheduledCourses(sch) {
    var byCode = Object.create(null);
    var order = [];
    pickList(sch, ["picks"], null).forEach(function (p) {
      var code = txt(p.code);
      if (!code) return;
      if (!byCode[code]) {
        byCode[code] = {
          code: code,
          name: txt(p.name) || nameOf(code),
          kinds: [],
          credits: null,
          timed: false,
        };
        order.push(code);
      }
      var rec = byCode[code];
      if (Array.isArray(p.meetings) && p.meetings.length) rec.timed = true;
      var kind = txt(p.kind);
      if (kind && rec.kinds.indexOf(kind) === -1) rec.kinds.push(kind);
      if (rec.credits === null) rec.credits = creditsNumber(p.credits);
    });
    return order
      .map(function (code) {
        return byCode[code];
      })
      .filter(function (rec) {
        return !rec.timed;
      });
  }

  /** ‏"ללא מועד קבוע: <שם> (<סוג>, N נ"ז)", פריט לכל קורס כזה. */
  function unscheduledLine(list) {
    return Tf("app.grid.unscheduled", {
      list: list
        .map(function (rec) {
          var kind = rec.kinds.join(", ");
          return rec.credits === null
            ? Tf("app.grid.unscheduledItemNoCredits", { name: rec.name, kind: kind })
            : Tf("app.grid.unscheduledItem", {
                name: rec.name,
                kind: kind,
                credits: Tf("app.credits.withUnit", { value: fmtNumber(rec.credits) }),
              });
        })
        .join(", "),
    });
  }

  /**
   * מה מרכיב את הניקוד, כטקסט לתיאור הכלי.
   * הניקוד הוא סכום של רכיבים חתומים: ``lecturer`` הוא בונוס חיובי וכל
   * השאר קנסות שליליים. לכן אין לו תקרה ידועה, והוא כמעט תמיד שלילי —
   * מספר שבלי ההסבר הזה אינו אומר דבר.
   */
  function scoreTitle(sch) {
    var b = (sch && sch.breakdown) || {};
    var lines = Object.keys(b).map(function (k) {
      var v = num(b[k], 0);
      return "· " + (BREAKDOWN_HE[k] || k) + ": " + (v > 0 ? "+" : "") + fmtNumber(v);
    });
    return Tf("app.schedule.scoreTitle", {
      total: fmtNumber(sch ? sch.score : 0),
      lines: lines.length ? lines.join("\n") + "\n" : "",
    });
  }

  /**
   * האם רכיב הניקוד הזה מוצג כאפס בכל אחת מהחלופות.
   * ההשוואה היא על הטקסט שיוצג ולא על הערך הגולמי: מדד ש-fmtNumber מעגל
   * ל-"0" בכל החלופות הוא עמודה של אפסים על המסך, ואין מה ללמוד ממנה.
   */
  function breakdownAlwaysZero(list, key) {
    return list.every(function (s) {
      return fmtNumber(num((s.breakdown || {})[key], 0)) === "0";
    });
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
    return Tf("app.overlap.meetingSide", {
      code: m.code,
      kind: m.kind,
      group: m.group_id,
      day: dayLetter(m.day),
      start: fmtTime(m.start),
      end: fmtTime(m.end),
    });
  }

  function meetingShort(m) {
    return Tf("app.overlap.meetingShort", {
      code: m.code,
      kind: m.kind,
      group: m.group_id,
    });
  }

  /** ‏"61753 אלגוריתמים (הרצאה)" — קוד, שם, ואז סוג השיעור. */
  function overlapSide(m) {
    return Tf("app.overlap.side", {
      code: txt(m.code),
      name: txt(m.name) || nameOf(m.code),
      kind: txt(m.kind),
    });
  }

  /**
   * שורה אחת לכל חפיפה: מי מול מי, מתי, ולמה זה הותר.
   * הכותרת שמעל כבר אומרת שמדובר בחפיפות מכוונות, ולכן השורה לא חוזרת
   * על כך, ומקדישה את המקום לשמות הקורסים ולסיבה.
   */
  function softConflictLine(a, b) {
    var optional = [];
    if (!attendanceRequired(a.code, a.kind)) {
      optional.push(txt(a.name) || nameOf(a.code));
    }
    if (!attendanceRequired(b.code, b.kind)) {
      optional.push(txt(b.name) || nameOf(b.code));
    }
    var why = optional.length
      ? Tf("app.overlap.whyOptional", {
          names: optional.join(T("app.overlap.whyJoin")),
        })
      : T("app.overlap.whyUnknown");
    // חלון החפיפה עצמו, לא טווח המפגש: זה מה שבאמת מתנגש.
    var from = Math.max(num(a.start, 0), num(b.start, 0));
    var to = Math.min(num(a.end, 0), num(b.end, 0));
    return Tf("app.overlap.row", {
      a: overlapSide(a),
      b: overlapSide(b),
      day: dayLetter(a.day),
      from: fmtTime(from),
      to: fmtTime(to),
      why: why,
    });
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

    // ‏השורות נבנות כאן, מהזוגות עצמם — ולא מ-``soft_conflict_report``.
    // הדיווח מהשרת הוא פרוזה שנכתבה למסוף: קודים בלי שם הקורס, "180 דקות",
    // ומקף רגיל במקום מקף שעות. כאן יש את שם הקורס, את חלון החפיפה עצמו
    // ואת הסיבה שהיא הותרה. הדיווח נשאר כגיבוי בלבד, למקרה שהשרת ראה
    // חפיפה שהזיהוי כאן לא ראה.
    var lines = pairs.map(function (pair) {
      return softConflictLine(pair[0], pair[1]);
    });
    var report = lines.length ? null : sch.soft_conflict_report;
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
    // ‏"חפיפה מכוונת אחת (2:00 שעות)" — הכותרת נושאת את הספירה ואת סך
    // הזמן, והשורות שמתחתיה נושאות את הפרטים. אין חזרה ביניהן.
    var head = info.minutes > 0
      ? (info.count === 1
          ? Tf("app.overlap.headOne", { span: fmtDuration(info.minutes) })
          : Tf("app.overlap.headMany", {
              count: info.count,
              span: fmtDuration(info.minutes),
            }))
      : (info.count === 1
          ? T("app.overlap.headOneNoSpan")
          : Tf("app.overlap.headManyNoSpan", { count: info.count }));
    setText(ui.softTitle, head);
    setText(ui.softSub, "");
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

  /**
   * מקרא הצבעים. משותף לשלב 5 ולשכבה — אותה פונקציית ``colorOf``, ולכן
   * אותו גוון לאותו קוד קורס בשני המקומות ובקובץ שנוצר במסוף.
   */
  function buildLegend(root, sch, opts) {
    if (!sch) return;
    var skip = (opts && opts.skip) || [];
    // הסימון החזותי של חפיפה מכוונת מוסבר כאן. מסגרת מקווקוות בלי מקרא
    // היא קישוט, לא מידע.
    var info = softConflictInfo(sch);
    if (info && info.count > 0) {
      root.appendChild(
        el("span", {
          class: "legend-chip legend-chip--overlap",
          text: T("app.grid.legendOverlap"),
        })
      );
    }
    var seen = Object.create(null);
    pickList(sch, ["picks"], null).forEach(function (p) {
      var code = txt(p.code);
      if (seen[code] || skip.indexOf(code) !== -1) return;
      seen[code] = true;
      // ‏DESIGN.md, "Results page", פריט 7: צבע, שם ונ"ז.
      var credits = creditsNumber(p.credits);
      var name = txt(p.name) || nameOf(code);
      root.appendChild(
        el("span", {
          class: "legend-chip c" + colorOf(code),
          data: { code: code },
          text: credits === null
            ? Tf("app.grid.legendChipNoCredits", { code: code, name: name })
            : Tf("app.grid.legendChip", {
                code: code,
                name: name,
                credits: Tf("app.credits.withUnit", { value: fmtNumber(credits) }),
              }),
        })
      );
    });
  }

  /**
   * טווח השעות של הרשת.
   *
   * הרשת מציגה את מה שמשובץ בפועל, בתוספת חצי שעה מכל צד — יום שנגמר
   * ב-15:50 לא צריך לצייר עד 20:00. המתג "הצג את כל השעות" שהחזיר את
   * היום המלא הוסר 2026-09-10; ראו DEFERRED.md.
   *
   * גם כשחוצים, הטווח נגזר מהמפגשים: מערכת שבאמת נמשכת 08:00–20:00 תצויר
   * במלואה, כולל החור הגדול באמצע. החור הזה **אמיתי**, והסתרתו הייתה
   * שקר — הקיצוץ מסיר שוליים ריקים, לא זמן שקיים.
   */
  function gridBounds(meetings) {
    if (!meetings.length) {
      return { start: GRID_DEFAULT_START, end: GRID_DEFAULT_END };
    }
    var first = Infinity;
    var last = -Infinity;
    meetings.forEach(function (m) {
      first = Math.min(first, num(m.start, 0));
      last = Math.max(last, num(m.end, 0));
    });
    // הטווח המלא: חלון היום, מורחב אם השיעורים חורגים ממנו.
    var fullStart = Math.min(GRID_DEFAULT_START, Math.floor(first / 60) * 60);
    var fullEnd = Math.max(GRID_DEFAULT_END, Math.ceil(last / 60) * 60);
    // חצי שעה מכל צד, מיושר לחצאי שעה כדי שתוויות השעה יישארו במקומן —
    // ו**לעולם לא מעבר לטווח המלא**. בלי החסימה הזאת יום שנגמר ב-19:50
    // היה מקבל ריפוד עד 20:30, כלומר רשת גבוהה מחלון היום עצמו. כשהיה
    // כאן מתג "הצג את כל השעות" זו הייתה תקלה חמורה יותר — המקוצצת יצאה
    // גבוהה מהמלאה — והחסימה נשארת גם בלעדיו.
    return {
      start: Math.max(fullStart, Math.floor((first - 30) / 30) * 30),
      end: Math.min(fullEnd, Math.ceil((last + 30) / 30) * 30),
    };
  }

  /** באילו ימים אין ולו שיעור אחד. */
  function emptyDays(meetings) {
    var used = Object.create(null);
    meetings.forEach(function (m) {
      used[num(m.day, 0)] = true;
    });
    return DAYS.filter(function (d) {
      return !used[d];
    });
  }

  /**
   * קוד חדר לתצוגה: ‏"709 L" -> "L 709".
   *
   * הידיעון שומר מספר ואז אות בניין, ואיש בבראודה לא אומר חדר ככה.
   * ההיפוך נעשה **בתצוגה בלבד** — הערך השמור אינו משתנה, וכל השוואה
   * מול הנתונים חייבת להשתמש בו ולא במה שמופיע על המסך.
   *
   * מה שאחרי הקוד נשאר במקומו: ‏"102 M מע'" -> "M 102 מע'".
   * מחרוזת שאינה בתבנית הזאת מוחזרת כמות שהיא — עדיף להציג משהו לא
   * מהופך מאשר לנחש.
   */
  var ROOM_RE = /^(\d+)\s+([A-Za-z]+)(.*)$/;

  function formatRoom(raw) {
    var text = txt(raw).trim();
    var m = ROOM_RE.exec(text);
    return m ? m[2] + " " + m[1] + m[3] : text;
  }

  /** הערך השמור, בלי היפוך — למי שצריך להשוות מול הנתונים. */
  function rawRoomOf(m) {
    return [txt(m && m.building), txt(m && m.room)].filter(Boolean).join(" ");
  }

  /** הערך להצגה. */
  function roomOf(m) {
    return formatRoom(rawRoomOf(m));
  }

  /**
   * החדר כפי שהוא מוצג בבלוק: הקוד ("L 706") כיחידה אחת שאינה נשברת, ומה
   * שאחריו ("מע' רשתות") כטקסט רגיל שרשאי להישבר. קוד שנשבר באמצע נקרא
   * כשני דברים — "L" בשורה אחת ו-"706" בשורה הבאה.
   *
   * ‏מחרוזת שאינה בתבנית "מספר אות" מוצגת כמות שהיא, בלי איסור שבירה: אין
   * בה קוד להגן עליו, ושם חדר ארוך בלי שבירה היה גולש מהבלוק.
   */
  function roomNode(m) {
    var text = roomOf(m);
    var parts = ROOM_RE.exec(txt(rawRoomOf(m)).trim());
    if (!parts) return el("span", { class: "ev-room" }, [ltrCode(text)]);
    var code = ltrCode(parts[2] + " " + parts[1]);
    setClass(code, "code--id", true);
    var rest = txt(parts[3]).trim();
    return el("span", { class: "ev-room" }, [
      code,
      rest ? document.createTextNode(" ") : null,
      rest ? el("span", { class: "ev-room-note", text: rest }) : null,
    ]);
  }

  /**
   * מזהה לטיני בתוך שורה עברית — קוד חדר, מספר קבוצה, קוד קורס.
   *
   * ‏<bdi> לבדו מבודד את הרצף אבל משאיר את כיוונו ל-``dir=auto``, שנקבע
   * לפי התו החזק הראשון. במחרוזת כמו "709 L" התו הראשון הוא ספרה — חלשה —
   * ובהקשר ימין-לשמאל הרצף כולו התהפך ל-"L 709". ‏dir="ltr" מפורש קובע
   * את הכיוון במקום לנחש אותו, ולכן הקוד מוצג בדיוק כפי שהוא שמור.
   */
  function ltrCode(text) {
    return el("bdi", { class: "code", attrs: { dir: "ltr" }, text: txt(text) });
  }

  function buildGrid(root, sch, soft) {
    var meetings = scheduleMeetings(sch);
    var bounds = gridBounds(meetings);
    var gridStart = bounds.start;
    var gridEnd = bounds.end;
    if (gridEnd <= gridStart) gridEnd = gridStart + 60;
    var slots = Math.ceil((gridEnd - gridStart) / SLOT_MINUTES);
    var blank = emptyDays(meetings);
    var blankSet = Object.create(null);
    blank.forEach(function (d) {
      blankSet[d] = true;
    });

    // יום ריק מצטמצם לרצועה צרה במקום לתפוס עמודה מלאה של כלום. הוא לא
    // נעלם: המערכת השבועית חייבת להיראות כשבוע, וגם "אין שיעורים ביום ו׳"
    // הוא מידע.
    root.style.setProperty(
      "grid-template-columns",
      "var(--time-col) " +
        DAYS.map(function (d) {
          return blankSet[d] ? "var(--day-empty)" : "minmax(var(--day-min), 1fr)";
        }).join(" ")
    );

    root.appendChild(el("div", { class: "hd", text: T("app.grid.hourHeader") }));
    DAYS.forEach(function (d) {
      root.appendChild(
        el(
          "div",
          {
            class: "hd" + (blankSet[d] ? " is-empty" : ""),
            attrs: { title: blankSet[d] ? T("app.grid.emptyDay") : dayName(d) },
          },
          [
            el("span", { text: Tf("app.grid.dayHeader", { day: dayLetter(d) }) }),
            blankSet[d]
              ? el("span", { class: "hd-empty", text: T("app.grid.emptyDay") })
              : null,
          ]
        )
      );
    });

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
            class:
              "slot" +
              (onHour ? " hour" : "") +
              (blankSet[DAYS[d]] ? " is-empty" : ""),
            style: {
              "grid-row": String(i + 2),
              "grid-column": String(DAYS[d] + 1),
            },
          })
        );
      }
    }

    // ‏בלוק לכל מפגש. חפיפה מכוונת חוזרת להיות שתי עמודות בחצי רוחב:
    // מיזוג לבלוק אחד הסתיר **אילו** שני קורסים מתנגשים, וזו בדיוק
    // השאלה שעומדת להכרעה. מה שהפך את החצאים לבלתי קריאים היה עומס
    // הטקסט, והוא ירד — לא הרוחב.
    var lanes = assignLanes(meetings);
    var marks = (soft && soft.marks) || {};
    meetings.forEach(function (m) {
      var key = meetingKey(m);
      var from = num(m.start, 0);
      var to = num(m.end, 0);
      var startSlot = Math.floor((from - gridStart) / SLOT_MINUTES);
      var endSlot = Math.ceil((to - gridStart) / SLOT_MINUTES);
      if (endSlot <= startSlot) endSlot = startSlot + 1;
      var clash = txt(marks[key]);

      var style = {
        "grid-row": startSlot + 2 + " / " + (endSlot + 2),
        "grid-column": String(m.day + 1),
      };
      var lane = lanes[key];
      if (lane && lane.lanes > 1) {
        style["margin-inline-start"] =
          ((lane.lane * 100) / lane.lanes).toFixed(2) + "%";
        style["margin-inline-end"] =
          (((lane.lanes - lane.lane - 1) * 100) / lane.lanes).toFixed(2) + "%";
      }

      var name = txt(m.name) || nameOf(m.code);
      var room = roomOf(m);
      var lecturer = txt(m.lecturer);
      var label = Tf("app.grid.openDetail", {
        name: name,
        day: dayLetter(m.day),
        from: fmtTime(from),
        to: fmtTime(to),
        room: room || T("app.detail.noRoom"),
      });
      if (clash) {
        var others = overlapPartners(m, meetings, marks)
          .slice(1)
          .map(function (o) {
            return txt(o.name) || nameOf(o.code);
          });
        // הצד השני בשם ולא בקוד: מי שמאזין לדף שומע את אותו מידע שמי
        // שרואה אותו מקבל משני הבלוקים זה לצד זה.
        label +=
          " · " +
          Tf("app.grid.clashSummary", {
            list: others.length ? others.join(", ") : clash,
          });
      }

      // ‏שלוש שורות, ואף אחת אינה יורדת (DESIGN.md, "Results page", 5):
      // ‏(1) שם הקורס, (2) סוג · שעה, (3) מרצה · חדר. גובה השעה נמדד כך
      // שכל בלוק מציג את שלושתן במלואן — ראו sizeGrid().
      var sep = function (a, b) {
        return a && b ? document.createTextNode(" · ") : null;
      };
      var kindEl = txt(m.kind) ? el("span", { class: "ev-kind", text: txt(m.kind) }) : null;
      var timeEl = el("span", {
        class: "cell-time",
        text: fmtTime(from) + "–" + fmtTime(to),
      });
      // השם המלא, ונשבר לשתי שורות אם צריך. קיצור ל"ד״ר סוקולובסקי"
      // חוסך שורה אבל מוחק בדיוק את מה שמבדיל בין שני מרצים באותו שם
      // משפחה — וזה מה שבוחרים לפיו.
      var lectEl = lecturer ? el("span", { class: "ev-lect", text: lecturer }) : null;
      var roomEl = room ? roomNode(m) : null;

      // ‏<button> ולא <div>: מספר הקבוצה נמצא רק בפאנל, ולכן חייבת להיות
      // אליו דרך במקלדת.
      var block = el(
        "button",
        {
          class: "ev c" + colorOf(m.code) + (clash ? " is-soft" : ""),
          style: style,
          attrs: { type: "button", "aria-label": label, title: label },
          data: { fk: "ev-" + key, rows: endSlot - startSlot },
          on: {
            click: function () {
              // החפיפה נפתחת עם שני הצדדים, גם כשלוחצים על אחד מהם.
              openMeetingDetail(overlapPartners(m, meetings, marks), !!clash);
            },
          },
        },
        [
          el("b", { class: "ev-line ev-name", text: name }),
          el("span", { class: "ev-line ev-when" }, [
            kindEl,
            sep(kindEl, timeEl),
            timeEl,
            // תג החפיפה בסוף השורה, ולא שורה רביעית משלו.
            clash
              ? el("span", { class: "ev-badge", text: T("app.grid.clashBadge") })
              : null,
          ]),
          lectEl || roomEl
            ? el("span", { class: "ev-line ev-who" }, [lectEl, sep(lectEl, roomEl), roomEl])
            : null,
        ]
      );
      root.appendChild(block);
    });
  }

  /** גיל בימים של חותמת ISO, או null אם אי אפשר לקרוא אותה. */
  function ageInDays(stamp) {
    var text = txt(stamp);
    if (!text) return null;
    var when = Date.parse(text);
    if (isNaN(when)) return null;
    return (Date.now() - when) / 86400000;
  }

  /** תאריך היום כ-‏"5.9.2026" — הסדר שבו כותבים תאריך בעברית. */
  function todayLabel() {
    var d = new Date();
    return d.getDate() + "." + (d.getMonth() + 1) + "." + d.getFullYear();
  }

  /** מפגש, ואיתו מי שחופף לו בכוונה — כדי שהפאנל יראה את שני הצדדים. */
  function overlapPartners(m, meetings, marks) {
    if (!txt(marks[meetingKey(m)])) return [m];
    return [m].concat(
      meetings.filter(function (other) {
        if (other === m) return false;
        if (other.day !== m.day) return false;
        if (other.start >= m.end || m.start >= other.end) return false;
        return !!txt(marks[meetingKey(other)]);
      })
    );
  }

  /**
   * גובה השעה נגזר מהתוכן: הגובה הקטן ביותר שבו **כל** בלוק ברשת מציג את
   * שלוש השורות שלו במלואן. שום שורה אינה יורדת ושום דבר אינו נחתך
   * (DESIGN.md, "Results page", פריט 5, 2026-09-30).
   *
   * ‏החליף את fitBlocks(), שהוריד שורות מבלוק שלא נכנס. הוא רץ בתוך
   * renderScheduleStep, מיד אחרי הבנייה — ולכן מדד פריסה שעוד לא הייתה
   * הסופית: הגופן Heebo נטען אחריו ורחב מגופן הגיבוי, והרשת עוד לא הייתה
   * ברוחבה. הוא מצא "נכנס", לא רץ שוב, והבלוק הציג חצי שורה חתוכה
   * (DEFERRED.md, "Grid blocks ship with lecturer names sliced in half").
   * כאן המדידה רצה אחרי הפריסה — ב-requestAnimationFrame — ושוב בכל פעם
   * שהיא יכולה להשתנות: שינוי רוחב (ResizeObserver), סיום טעינת גופן,
   * ומעבר להדפסה. ראו wireRefit().
   *
   * ‏איך: לרגע אחד כל בלוק מקבל את גובהו הטבעי (‎.is-measuring‎ ב-CSS), והגובה
   * הזה מחולק במספר משבצות ה-15 דקות שהבלוק תופס. המקסימום הוא ‎--slot-h‎
   * של הרשת הזו. הרוחב אינו תלוי בגובה, ולכן מדידה אחת מספיקה — ובכל זאת
   * התוצאה נבדקת, ומשבצת מתווספת פיקסל אם בלוק כלשהו עדיין גולש.
   */
  //: רצפה בלבד, לא גובה קבוע: רשת שכל שיעוריה ארוכים לא נדחסת עד שתוויות
  //: השעה נוגעות זו בזו.
  var SLOT_H_FLOOR = 12;

  function sizeGrid(root) {
    if (!root) return;
    var blocks = root.querySelectorAll(".ev");
    // ‏רשת ריקה או מוסתרת: אין מה למדוד, ומדידה של אפס הייתה קובעת גובה
    // אפס. כשהיא תופיע, ה-ResizeObserver יקרא לכאן שוב.
    if (!blocks.length || !root.getClientRects().length) {
      root.style.removeProperty("--slot-h");
      return;
    }
    setClass(root, "is-measuring", true);
    var need = SLOT_H_FLOOR;
    for (var i = 0; i < blocks.length; i++) {
      var b = blocks[i];
      var rows = Math.max(1, num(b.dataset.rows, 1));
      var cs = getComputedStyle(b);
      var outer =
        b.getBoundingClientRect().height +
        num(parseFloat(cs.marginTop), 0) +
        num(parseFloat(cs.marginBottom), 0);
      need = Math.max(need, outer / rows);
    }
    setClass(root, "is-measuring", false);

    var slot = Math.ceil(need - 0.01);
    root.style.setProperty("--slot-h", slot + "px");
    // ‏scrollHeight ו-clientHeight מעוגלים לפיקסל שלם, ולכן בלוק שנכנס
    // בדיוק יכול להיראות גולש בחצי פיקסל. לא מנחשים: בודקים ומוסיפים.
    for (var guard = 0; guard < 4 && anyBlockOverflows(blocks); guard++) {
      slot += 1;
      root.style.setProperty("--slot-h", slot + "px");
    }
  }

  function anyBlockOverflows(blocks) {
    for (var i = 0; i < blocks.length; i++) {
      if (blocks[i].scrollHeight > blocks[i].clientHeight) return true;
    }
    return false;
  }

  /** שתי הרשתות: שלב 5 והשכבה — ובהדפסה, עמוד אחד כשאפשר. */
  function sizeGrids() {
    if (gridSizingFrame && window.cancelAnimationFrame) {
      window.cancelAnimationFrame(gridSizingFrame);
    }
    gridSizingFrame = 0;
    sizeGrid(ui.grid);
    sizeGrid(ui.overlayGrid);
    fitGridToPage();
  }

  //: ‏A4 לאורך: הצד הארוך הוא 297 מ"מ, וזה גובה העמוד המודפס. ‏@page
  //: מכריז בדיוק על הגודל הזה (style.css), ולכן זה לא ניחוש.
  var PRINT_PAGE_PX = (297 * 96) / 25.4;
  var PRINT_FONT_MAX = 13;
  var PRINT_FONT_MIN = 10;
  var PRINT_FONT_STEP = 0.5;

  /**
   * עמוד אחד כשאפשר — על ידי גופן, לא על ידי השמטה.
   *
   * רשת שנשפכת לעמוד שני נשברת באמצע שעה, ושורת כותרות הימים נשארת
   * מאחור: אין דרך ב-CSS לחזור על שורת כותרות ברשת grid (‏thead עושה זאת
   * בטבלה, ‏position: fixed אינו חוזר בעמודים נוספים ב-Chrome). לכן הפתרון
   * אינו לנהל את השבירה אלא לא להגיע אליה.
   *
   * ‏עד 2026-09-30 הפונקציה הקטינה את גובה המשבצת עד 12px, ו-fitBlocks()
   * הוריד את השורות שלא נכנסו. עכשיו גובה השעה נגזר מהתוכן (sizeGrid), ולכן
   * מה שמוקטן הוא גופן הבלוקים — בצעדים של 0.5px, מ-13px ועד 10px — ואחרי כל
   * צעד גובה השעה נמדד מחדש, ושלוש השורות נשארות בכל בלוק. זה החריג היחיד
   * לרצפת ה-13px, והוא חל על הנייר בלבד (DESIGN.md, "Results page", Print).
   *
   * ‏כשגם 10px אינו מספיק, הגופן חוזר ל-13px והדף מתחלק לשני עמודים: עמוד
   * אחד שקשה לקרוא אינו שיפור על שני עמודים קריאים — ואם העמוד האחד אינו
   * מתקבל בתמורה, אין סיבה לשלם בקריאות.
   */
  function fitGridToPage() {
    var grid = ui.grid;
    if (!grid) return;
    grid.style.removeProperty("--ev-font-print");
    if (!window.matchMedia || !window.matchMedia("print").matches) return;
    if (!grid.querySelector(".ev")) return;
    for (var f = PRINT_FONT_MAX; f >= PRINT_FONT_MIN; f -= PRINT_FONT_STEP) {
      grid.style.setProperty("--ev-font-print", f + "px");
      sizeGrid(grid);
      if (document.body.scrollHeight <= PRINT_PAGE_PX) return;
    }
    grid.style.removeProperty("--ev-font-print");
    sizeGrid(grid);
  }

  /**
   * מדידה בפריים הבא, אחרי שהפריסה של הציור הנוכחי קרתה — ולפני שהוא
   * נצבע, כך שהגובה הזמני לעולם אינו נראה. כמה בקשות באותו פריים הן מדידה
   * אחת.
   */
  var gridSizingFrame = 0;

  function requestGridSizing() {
    if (gridSizingFrame) return;
    if (!window.requestAnimationFrame) {
      sizeGrids();
      return;
    }
    gridSizingFrame = window.requestAnimationFrame(function () {
      gridSizingFrame = 0;
      sizeGrids();
    });
  }


  /* --- ויתורים נמדדים ------------------------------------------------ */

  /** שם האילוץ, בלשון "לוותר על X". */
  function relaxLabel(item) {
    var d = item.detail || {};
    if (item.kind === "friday") return T("app.relax.kind.friday");
    if (item.kind === "earliest")
      return Tf("app.relax.kind.earliest", { time: fmtTime(num(d.was, 0)) });
    if (item.kind === "latest")
      return Tf("app.relax.kind.latest", { time: fmtTime(num(d.was, 0)) });
    if (item.kind === "blocked")
      return Tf("app.relax.kind.blocked", {
        day: dayName(num(d.day, 0)),
        from: fmtTime(num(d.start, 0)),
        to: fmtTime(num(d.end, 0)),
      });
    return txt(item.kind);
  }

  /** שם האילוץ בלשון "מה מוחזר" — לכפתור הביטול. */
  function relaxRestoreName(kind, detail) {
    var d = detail || {};
    if (kind === "friday") return T("app.relax.restoreName.friday");
    if (kind === "earliest")
      return Tf("app.relax.restoreName.earliest", { time: fmtTime(num(d.was, 0)) });
    if (kind === "latest")
      return Tf("app.relax.restoreName.latest", { time: fmtTime(num(d.was, 0)) });
    if (kind === "blocked")
      return Tf("app.relax.restoreName.blocked", {
        day: dayName(num(d.day, 0)),
        from: fmtTime(num(d.start, 0)),
        to: fmtTime(num(d.end, 0)),
      });
    return txt(kind);
  }

  /**
   * המחיר, כפי שנמדד מהמערכות שהוויתור באמת פתח.
   *
   * ‏"12 מערכות" בלי "וכולן עם יום שישי" מוכר את הוויתור בלי המחיר שלו.
   */
  function relaxCost(cost) {
    var c = cost || {};
    var n = num(c.n, 0);
    var of = num(c.of, 0);
    if (c.metric === "friday") {
      if (!n) return T("app.relax.cost.fridayNone");
      return n >= of
        ? T("app.relax.cost.fridayAll")
        : Tf("app.relax.cost.fridaySome", { n: n, of: of });
    }
    if (c.metric === "starts_at")
      return Tf("app.relax.cost.startsAt", { time: fmtTime(num(c.minutes, 0)) });
    if (c.metric === "ends_at")
      return Tf("app.relax.cost.endsAt", { time: fmtTime(num(c.minutes, 0)) });
    if (c.metric === "uses_window") {
      if (!n) return T("app.relax.cost.windowNone");
      return n >= of
        ? T("app.relax.cost.windowAll")
        : Tf("app.relax.cost.windowSome", { n: n, of: of });
    }
    return "";
  }

  /** כמה נפתח — או למה אין מספר. ‏null אינו 0. */
  function relaxOpens(item) {
    if (item.schedules === null || item.schedules === undefined)
      return { text: T("app.relax.unmeasured"), title: T("app.relax.unmeasuredTitle") };
    if (!item.schedules) return { text: T("app.relax.useless"), title: "" };
    return {
      text:
        item.schedules === 1
          ? T("app.relax.opensOne")
          : Tf("app.relax.opens", { n: item.schedules }),
      title: "",
    };
  }

  /**
   * מחיל ויתור, וזוכר **את ההיפוך שלו בלבד**.
   *
   * לא צילום של כל ההעדפות: ביטול שמשחזר מצב שלם היה דורס כל שינוי אחר
   * שנעשה בינתיים. היפוך ממוקד לא יכול לעשות את זה — הוא נוגע רק
   * באילוץ שהורפה.
   */
  function applyRelaxation(item) {
    var deltas = [item.apply];
    if (item.combines_with) deltas.push(item.combines_with.apply);
    var patch = {};
    var restores = [];
    deltas.forEach(function (delta, i) {
      var kind = i === 0 ? item.kind : item.combines_with.kind;
      var detail = i === 0 ? item.detail : item.combines_with.detail;
      restores.push({ kind: kind, detail: detail, was: relaxSnapshot(delta) });
      Object.keys(delta).forEach(function (key) {
        if (key === "forbid_friday") patch.forbidFriday = delta[key];
        else if (key === "earliest") patch.earliest = delta[key];
        else if (key === "latest") patch.latest = delta[key];
        else if (key === "drop_blocked_window") {
          var w = delta[key];
          patch.blocked = (patch.blocked || state.blocked || []).filter(function (b) {
            return !(b[0] === w[0] && b[1] === w[1] && b[2] === w[2]);
          });
        }
      });
    });
    runtime.lastRelax = { restores: restores, applied: patch };
    setState(patch);
    toast(
      Tf("app.relax.applied", {
        what: restores.map(function (r) { return relaxRestoreName(r.kind, r.detail); })
                      .join(" ו"),
        n: num(item.schedules, 0),
      }),
      "ok"
    );
  }

  /** מה היה לפני הוויתור — ערך יחיד, לא מצב שלם. */
  function relaxSnapshot(delta) {
    var was = {};
    Object.keys(delta).forEach(function (key) {
      if (key === "forbid_friday") was.forbidFriday = state.forbidFriday;
      else if (key === "earliest") was.earliest = state.earliest;
      else if (key === "latest") was.latest = state.latest;
      else if (key === "drop_blocked_window") was.window = delta[key];
    });
    return was;
  }

  /**
   * האם הביטול עדיין תקף.
   *
   * תקף = האילוץ עדיין נמצא במצב שהוויתור הביא אותו אליו. אם שינית אותו
   * שוב בעצמך, הביטול **נעלם** — ביטול שמחזיר מצב שכבר לא קיים גרוע
   * מהיעדר ביטול.
   */
  function relaxUndoValid() {
    var last = runtime.lastRelax;
    if (!last) return false;
    var patch = last.applied || {};
    var keys = Object.keys(patch);
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      if (k === "blocked") {
        if ((state.blocked || []).length !== (patch.blocked || []).length) return false;
      } else if (state[k] !== patch[k]) {
        return false;
      }
    }
    return true;
  }

  /** מחזיר בדיוק את מה שהורפה, ותו לא. */
  function undoRelaxation() {
    var last = runtime.lastRelax;
    if (!last || !relaxUndoValid()) return;
    var patch = {};
    var names = [];
    last.restores.forEach(function (r) {
      names.push(relaxRestoreName(r.kind, r.detail));
      var was = r.was || {};
      if ("forbidFriday" in was) patch.forbidFriday = was.forbidFriday;
      if ("earliest" in was) patch.earliest = was.earliest;
      if ("latest" in was) patch.latest = was.latest;
      if (was.window) {
        patch.blocked = (patch.blocked || state.blocked || []).concat([was.window]);
      }
    });
    runtime.lastRelax = null;
    setState(patch);
    toast(Tf("app.relax.undone", { what: names.join(" ו") }), "ok");
  }

  /**
   * הודעת הביטול, במקום שרואים כשיש תוצאות.
   *
   * נעלמת מעצמה כשהאילוץ שהורפה שונה שוב ידנית — ראי ``relaxUndoValid``.
   * ביטול שמחזיר מצב שכבר אינו קיים גרוע מהיעדר ביטול.
   */
  function renderRelaxUndo() {
    if (!ui.relaxUndo) return;
    var ok = relaxUndoValid();
    setHidden(ui.relaxUndo, !ok);
    if (!ok) return;
    var names = (runtime.lastRelax.restores || []).map(function (r) {
      return relaxRestoreName(r.kind, r.detail);
    });
    rebuild(ui.relaxUndo, function (box) {
      box.appendChild(
        el("span", {
          class: "relax-undo-text",
          text: Tf("app.relax.undoNotice", { what: names.join(" ו") }),
        })
      );
      box.appendChild(
        el("button", {
          class: "btn btn-outline btn-sm",
          attrs: { type: "button" },
          data: { fk: "relax-undo" },
          // שם מה שחוזר, ולא "בטל".
          text: Tf("app.relax.undo", { what: names.join(" ו") }),
          on: { click: undoRelaxation },
        })
      );
    });
  }

  /** מצייר את הוויתורים שנמדדו. */
  function renderRelaxations(s) {
    if (!ui.relax) return;
    var data = (s && s.relaxations) || {};
    var items = pickList(data, ["items"], null);
    var pairs = data.pairs_only === true;
    setHidden(ui.relax, !items.length);
    if (!items.length) return;

    setText(ui.relaxTitle, pairs ? T("app.relax.titlePairs") : T("app.relax.title"));
    setText(ui.relaxIntro, pairs ? T("app.relax.introPairs") : T("app.relax.intro"));

    rebuild(ui.relaxList, function (box) {
      items.forEach(function (item, idx) {
        var opens = relaxOpens(item);
        var cost = relaxCost(item.cost);
        // זוג נכתב בשתי שורות עם סוגר, ולא במשפט אחד ארוך. זו השורה
        // הכי קשה לקריאה במסך הזה, והיא בדיוק זו שסטודנט/ית תקועים
        // מגיעים אליה — לכן היא מקבלת את המקום ולא חוסכת בו.
        var what = item.combines_with
          ? el("div", { class: "relax-pair" }, [
              el("span", { class: "relax-pair-line", text: relaxLabel(item) }),
              el("span", {
                class: "relax-pair-line",
                text: relaxLabel(item.combines_with),
              }),
              el("span", { class: "relax-pair-both", text: T("app.relax.pairBoth") }),
            ])
          : el("b", { text: relaxLabel(item) });

        var row = el("div", { class: "relax-row" }, [
          el("div", { class: "relax-what" }, [
            what,
            el("span", {
              class: "relax-opens" + (item.schedules ? "" : " is-quiet"),
              text: opens.text,
              attrs: opens.title ? { title: opens.title } : {},
            }),
            cost ? el("span", { class: "relax-cost", text: cost }) : null,
          ]),
          item.schedules
            ? el("button", {
                class: "btn btn-outline btn-sm",
                attrs: {
                  type: "button",
                  title: T("app.relax.applyTitle"),
                },
                data: { fk: "relax-" + idx },
                text: item.combines_with ? T("app.relax.pairApply") : T("app.relax.apply"),
                on: { click: function () { applyRelaxation(item); } },
              })
            : null,
        ]);
        box.appendChild(row);
      });
    });

    var checked = pickList(data, ["checked"], null);
    setText(
      ui.relaxChecked,
      checked.length
        ? Tf("app.relax.checkedNone", {
            list: checked.map(relaxLabel).join(", "),
          })
        : ""
    );
  }

  /* --- מצב חמשת השלבים ------------------------------------------------ */

  /**
   * מצב סעיף אחד: ‏"default" / "chosen" / "conflict".
   *
   * ‏conflict גובר תמיד — הגדרה שאי אפשר לקיים היא הדבר היחיד שדורש
   * פעולה, ולכן היא צריכה להיראות אחרת גם מסעיף שנבחר וגם מסעיף שלא.
   */
  function sectionState(key) {
    var s = runtime.solve;
    var conflict = false;
    if (key === "days") {
      conflict = !!(s && s.target_reachable === false);
    } else if (key === "courses") {
      conflict =
        pickList(s || {}, ["tied_missing"], null).length > 0 ||
        runtime.notOffered.length > 0;
    } else if (key === "lecturers") {
      conflict = pinCount() > 0 && !!s && schedules().length === 0;
    }
    if (conflict) return "conflict";
    return sectionIsDefault(key) ? "default" : "chosen";
  }

  /** האם יש בכלל ערך בתוך המפה — מפתח עם אובייקט או מערך ריק אינו בחירה. */
  function hasAnyEntry(map, isSet) {
    var m = map || {};
    return Object.keys(m).some(function (k) {
      return isSet(m[k]);
    });
  }

  /**
   * האם הסעיף עדיין מציג את ברירת המחדל.
   *
   * ‏משווים ערכים, ולא זוכרים נגיעה. ``state.touched`` היה דביק: מרגע
   * שנגעת בסעיף הוא נשאר ירוק לתמיד, גם אחרי שהחזרת הכול לברירת המחדל —
   * ולמי שחוזר/ת אחרי יום כל ארבעת הסעיפים היו ירוקים, כלומר הסימון חדל
   * לשאת מידע. זה בדיוק מה ששלב 5 בא לתקן.
   *
   * ‏ברירת המחדל של "קורסים" אינה רשימה ריקה אלא ההמלצה של הסמסטר, ולכן
   * הסטייה נמדדת במקור: הוספה ידנית או ביטול של קורס מומלץ.
   */
  function sectionIsDefault(key) {
    var b = runtime.baseline;
    if (!b) return true; // לפני bootstrap אין מול מה להשוות

    if (key === "year") {
      // ‏זהות, לא העדפה: אין ברירת מחדל להשוות אליה. אפור עד שנבחרו
      // שלושתם, ירוק אחריהם.
      return !identityChosen();
    }
    if (key === "courses") {
      // ‏אין סימון מראש, ולכן אין מקרה מיוחד: ריק = לא בחרה, מסומן = בחרה.
      return (state.codes || []).length === 0;
    }
    if (key === "days") {
      return (
        num(state.targetDays, null) === null &&
        !!state.forbidFriday === !!b.forbidFriday &&
        state.earliest === b.earliest &&
        state.latest === b.latest &&
        (state.blocked || []).length === 0
      );
    }
    if (key === "lecturers") {
      // ‏מפתח חסר = חובת נוכחות, ולכן רק ``false`` מפורש הוא ויתור.
      var waived = hasAnyEntry(state.attendance, function (byKind) {
        return Object.keys(byKind || {}).some(function (k) {
          return byKind[k] === false;
        });
      });
      var ranked = hasAnyEntry(state.ranked, function (list) {
        return Array.isArray(list) && list.length > 0;
      });
      var pinned = hasAnyEntry(state.pinned, function (byKind) {
        return Object.keys(byKind || {}).length > 0;
      });
      return !waived && !ranked && !pinned;
    }
    return true;
  }

  /**
   * מקפל שלבים שכבר היו מוכנים כשהגענו לעמוד.
   *
   * שלושה תנאים, וכולם נחוצים:
   *  1. ``runtime.restored`` — יש מצב שמור. בכניסה ראשונה אין מה לקפל,
   *     והעמוד צריך להיראות כאשף מלא.
   *  2. ``!runtime.userActed`` — עוד לא נגעו בכלום. אחרי הנגיעה הראשונה
   *     שום דבר לא נסגר מעצמו, כדי ששלב לא ייעלם באמצע עבודה בו.
   *  3. ``state.collapsed[key] === undefined`` — לא נקבעה העדפה מפורשת.
   *
   * השיקול נעשה פעם אחת לכל שלב (``runtime.autoCollapsed``), כי "הושלם"
   * של שלבים 3 ו-4 מגיע רק אחרי שהפתרון הראשון חוזר מהשרת — כמה ציורים
   * אחרי הטעינה.
   */
  function autoCollapseIfIdle(steps) {
    if (!runtime.restored || runtime.userActed) return;
    var changed = false;
    steps.forEach(function (step) {
      if (AUTO_COLLAPSE_STEPS.indexOf(step.key) === -1) return;
      if (runtime.autoCollapsed[step.key]) return;
      if (!step.complete || step.locked) return;
      runtime.autoCollapsed[step.key] = true;
      if (state.collapsed[step.key] === undefined) {
        state.collapsed[step.key] = true;
        changed = true;
      }
    });
    // שמירה בלבד: אנחנו כבר בתוך ציור, ו-setState היה מזמן ציור נוסף.
    if (changed) saveState();
  }

  /** שורת הסיכום של שלב 1: הזהות, ואחריה ההתמחות והמסלול — או מה שחסר. */
  function yearStepText() {
    var identity = usesPlanSemester()
      ? !identityChosen()
        ? T("app.steps.year.emptyIntake")
        : Tf("app.steps.year.selectedIntake", {
            intake: intakeLabel(),
            label: planSemesterLabel(),
          })
      : !identityChosen()
        ? T("app.steps.year.empty")
        : Tf("app.steps.year.selected", {
            year: YEAR_LABELS[state.studyYear] || "",
            term: txt(state.term),
          });
    if (!identityChosen()) return identity;
    var missing = trackMissing();
    if (missing) return Tf("app.steps.year.trackMissing", { what: missing });
    var track = [chosenSpecialization(), chosenRoute(), chosenSecondary()]
      .filter(Boolean)
      .join(" · ");
    return track ? Tf("app.steps.year.withTrack", { identity: identity, track: track }) : identity;
  }

  function renderStepStates() {
    var hasCodes = state.codes.length > 0;
    var hasData = runtime.courses.length > 0;
    // ‏שלב 4 היה נעול על ``hasData`` לבדו, ולכן מי שבחר/ה **רק** קורסים
    // שאין להם קבוצות נתקע/ה על "ממתין לנתוני הקבוצות" לנצח — וזו המתנה
    // למשהו שלא יגיע. כשלכל קוד שנבחר כבר יש תשובה (נתונים, או הסבר למה
    // אין), אין למה להמתין: השלב נפתח ומציג את ההסבר.
    var answered = allSelectedAnswered();
    var lecturersLocked = !hasData && !answered;
    var list = schedules();
    var s = runtime.solve;

    var steps = [
      {
        key: "year",
        // בחירת שנה+סמסטר היא שלב שלם גם כשאין לה סמסטר בתוכנית
        // (תוכנית קצרה מ-8 סמסטרים, קיץ, או אין תוכנית כלל).
        locked: false,
        // ‏תיבת התמחות/מסלול שמוצגת היא חובה: בלעדיה השלב אינו מושלם.
        complete: identityChosen() && !trackMissing(),
        // שנה וסמסטר בלבד. התרגום לסמסטר בתוכנית הלימודים יושב בשבב
        // שמתחת, ואמירתו כאן שוב הייתה אותה שורה פעמיים במרחק שורה.
        // ‏מסלול עם מועדי כניסה אומר כאן מועד + תווית הסמסטר, כי שנה
        // אין לו: "חורף · סמסטר 4 · סמסטר א׳ (חורף)".
        text: yearStepText(),
      },
      {
        key: "courses",
        // ‏רשימת הקורסים נגזרת מהמסלול ומהסמסטר. בלעדיהם אין מה להציע,
        // ולכן השלב נעול עם שורה שאומרת מה חסר — אותו דפוס בדיוק כמו
        // "‏ממתין לקורסים" בשלבים שאחריו.
        locked: !identityChosen(),
        complete: identityChosen() && hasCodes,
        text: !identityChosen()
          ? T("app.steps.courses.waitingForIdentity")
          : hasCodes
          ? Tf("app.steps.courses.selected", {
              count: state.codes.length,
              credits: totalCreditsText({ unit: true, short: true }),
            })
          : catalogFallbackActive()
          ? T("app.steps.courses.emptyCatalog")
          : T("app.steps.courses.empty"),
      },
      {
        key: "days",
        locked: !hasCodes,
        complete: hasCodes && !!s,
        // ‏בלי יעד אין מה להציב ב-"יעד {target} ימים" — השורה הייתה אומרת
        // ‏"יעד null ימים". אומרים שהיעד עוד לא נבחר.
        text: !hasCodes
          ? T("app.steps.days.waitingForCourses")
          : num(state.targetDays, null) === null
          ? T("app.days.pickTarget")
          : s && num(s.min_days, null) !== null
          ? Tf("app.steps.days.targetWithMin", {
              target: state.targetDays,
              min: s.min_days,
            })
          : Tf("app.steps.days.target", { target: state.targetDays }),
      },
      {
        key: "lecturers",
        locked: lecturersLocked,
        complete: hasData && (rankedCount() > 0 || pinCount() > 0 || list.length > 0),
        // שני החלקים נאמרים תמיד, גם כשהם אפס: כשהשלב מקופל זו כל האמירה
        // שנשארת עליו, ו"ללא נעיצות" הוא מידע — היעדרו אינו.
        text: !hasData
          ? lecturersLocked
            ? T("app.steps.lecturers.waitingForData")
            : T("app.steps.lecturers.noGroupData")
          : Tf("app.steps.lecturers.summary", {
              ranked:
                rankedCount() === 0
                  ? T("app.steps.lecturers.ranked.none")
                  : rankedCount() === 1
                  ? T("app.steps.lecturers.ranked.one")
                  : Tf("app.steps.lecturers.ranked.many", { count: rankedCount() }),
              pins:
                pinCount() === 0
                  ? T("app.steps.lecturers.pins.none")
                  : pinCount() === 1
                  ? T("app.steps.lecturers.pins.one")
                  : Tf("app.steps.lecturers.pins.many", { count: pinCount() }),
            }),
      },
      {
        key: "schedule",
        locked: !hasCodes,
        complete: list.length > 0,
        text: !hasCodes
          ? T("app.steps.schedule.waitingForCourses")
          : list.length
          ? Tf("app.steps.schedule.showing", {
              index: clamp(state.activeSchedule, 0, list.length - 1) + 1,
              total: list.length,
            })
          : runtime.solveBusy
          ? T("app.steps.schedule.solving")
          : T("app.steps.schedule.none"),
      },
    ];

    autoCollapseIfIdle(steps);

    var activeAssigned = false;
    steps.forEach(function (step) {
      var node = ui.steps[step.key];
      setText(ui.stepStates[step.key], step.text);
      // שורת הסיכום היא אותו טקסט בדיוק — היא פשוט זו שנראית כשמקופל,
      // ומשמשת גם כשם הנגיש של הכפתור.
      setText(ui.stepSummaries[step.key], step.text);
      if (!node) return;
      var isActive = false;
      if (!activeAssigned && !step.locked && !step.complete) {
        isActive = true;
        activeAssigned = true;
      }
      // שלב נעול הוא ריק ממילא, ואין טעם לקפל אותו.
      var collapsed = stepCollapsed(step.key) && !step.locked;
      var mark = COLLAPSIBLE_STEPS.indexOf(step.key) === -1
        ? null
        : sectionState(step.key);
      setClass(node, "is-locked", step.locked);
      setClass(node, "is-default", mark === "default" && !step.locked);
      setClass(node, "is-conflict", mark === "conflict" && !step.locked);
      // ‏✓ ירוק רק כשבאמת נבחר משהו — ולא על כל סעיף מהרגע הראשון.
      setClass(
        node,
        "is-complete",
        (mark === "chosen" || mark === null) && step.complete && !step.locked
      );
      setClass(node, "is-active", isActive);
      setClass(node, "is-collapsed", collapsed);
      var toggle = ui.stepToggles[step.key];
      if (toggle) toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      if (step.locked) node.setAttribute("aria-disabled", "true");
      else node.removeAttribute("aria-disabled");
    });
    if (!activeAssigned) {
      var last = ui.steps.schedule;
      if (last) setClass(last, "is-active", true);
    }
    // ‏מאותם טקסטים בדיוק: שבב ההגדרות אינו ניסוח שני של סיכום השלב.
    renderSettingsPills(steps, hasCodes && !!s);
  }

  /**
   * מסמן ויזואלית כל אלמנט שנותר בו מפתח נוסח חסר.
   *
   * ‏T() כבר מחזיר ⟦path⟧ ורושם ליומן, אבל מחרוזת בתוך טקסט עדיין יכולה
   * להיקרא כמו תוכן. כאן היא מקבלת מסגרת אדומה, וגם ``document.title``
   * מקבל סימן — כדי שגם צילום מסך יסגיר את התקלה.
   */
  function markMissingStrings() {
    var marked = document.querySelectorAll(".missing-string");
    for (var i = 0; i < marked.length; i++) {
      setClass(marked[i], "missing-string", false);
    }
    // הסימון הוויזואלי הוא כלי פיתוח. במצב רגיל אין מסגרות אדומות
    // על המסך — רק שורה ביומן.
    if (!DEBUG) return;
    if (!MISSING_STRINGS.length && !STRINGS_EMPTY) return;
    var walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      null
    );
    var node;
    while ((node = walker.nextNode())) {
      if (node.nodeValue && node.nodeValue.indexOf("⟦") !== -1) {
        if (node.parentElement) setClass(node.parentElement, "missing-string", true);
      }
    }
  }

  /* =====================================================================
   * 11. הפעלה
   * ===================================================================== */

  /**
   * מדידה חוזרת של גובה השעה בכל פעם שהפריסה יכולה להשתנות: רוחב, גופן
   * והדפסה. ראו sizeGrid().
   */
  function wireRefit() {
    window.addEventListener("resize", requestGridSizing);
    // ‏הרוחב של מיכל הרשת משתנה גם בלי שינוי חלון — כשהשכבה נפתחת, או
    // כשהמיכל יוצא ממצב מוסתר. ‏ResizeObserver רואה את זה; resize לא.
    // ‏המדידה נדחית לפריים הבא ולא רצה בתוך ה-callback, כדי שהשינוי שהיא
    // עושה בגובה לא ייצור לולאת ResizeObserver.
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(requestGridSizing);
      [ui.gridScroll, ui.overlayGridScroll].forEach(function (node) {
        if (node) ro.observe(node);
      });
    }
    // ‏Heebo רחב מגופן הגיבוי. מדידה שקדמה לטעינתו קבעה גובה לטקסט צר
    // מזה שבסוף צויר — זו אחת משתי הסיבות לחיתוך שב-DEFERRED.
    if (document.fonts) {
      if (document.fonts.ready) document.fonts.ready.then(requestGridSizing);
      if (document.fonts.addEventListener) {
        document.fonts.addEventListener("loadingdone", requestGridSizing);
      }
    }
    // ‏matchMedia ולא beforeprint: כשהאירוע הזה נורה גיליון ההדפסה כבר
    // חל, ולכן המדידה היא של הנייר. ב-beforeprint היא עדיין של המסך.
    // ‏כאן בלי השהיה — ההדפסה יכולה להיצלם לפני הפריים הבא.
    if (!window.matchMedia) return;
    var mq = window.matchMedia("print");
    if (mq.addEventListener) mq.addEventListener("change", sizeGrids);
    else if (mq.addListener) mq.addListener(sizeGrids);
  }

  function boot() {
    runtime.restored = loadState();
    // לאיזה סמסטר הבחירה השמורה שייכת. האימוץ החד-פעמי ב-
    // ``applyRecommendedDefaults`` נשען על זה: בחירה ששייכת לסמסטר 5 אינה
    // תשובה לשאלה "מה מומלץ בסמסטר 3", ואימוץ שלה שם היה רושם את כל ההמלצה
    // החדשה כ"בוטלה" ומשאיר את הרשימה ריקה.
    runtime.adoptSemester = runtime.restored ? txt(state.semester) : "";
    cacheElements();
    wireEvents();
    wireRefit();
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
  window.slotwise = {
    // ‏היפוך קוד החדר, חשוף לבדיקה: "709 L" -> "L 709".
    formatRoom: formatRoom,
    // ‏מה שבדיקת הדפדפן שואלת: אילו מפתחות נוסח לא נמצאו.
    missingStrings: function () {
      return MISSING_STRINGS.slice();
    },
    stringsEmpty: function () {
      return STRINGS_EMPTY;
    },
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
