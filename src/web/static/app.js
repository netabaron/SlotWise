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
  var SCRAPE_POLL_MS = 2000;
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
      // והמסלול שלו. מספר הסמסטר לבדו אינו מזהה המלצה: החלפת מסלול אינה
      // משנה אותו, וסטודנט/ית שעברו מהנדסת תוכנה לאזרחית נשארו עם רשימת
      // התוכנה מסומנת מתחת לקורסי האזרחית.
      autoProgram: "",
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
      // קיפול שלבים: {מפתח שלב: true/false}. **רק בחירה מפורשת** נרשמת כאן,
      // ולכן מפתח חסר פירושו "לא הוכרע" — וזה מה שמתיר לקיפול האוטומטי
      // לפעול פעם אחת בלי לדרוס העדפה שנקבעה ביד.
      collapsed: {},
      // ‏"הצג את כל השעות" — העדפת תצוגה, נשמרת כמו הקיפול.
      allHours: false,
      // באילו סעיפים המשתמש/ת באמת בחרו משהו. ‏✓ ירוק שמופיע תמיד
      // אינו אומר דבר; זה מה שמבדיל בחירה מברירת מחדל.
      touched: {},
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
    // ‏false = הנ"ז שחולצה מהשנתון אינה שווה לסה"כ שהשנתון מדפיס.
    // ‏null = אין בדיקה כזאת לתוכנית הזאת.
    semesterReconciles: null,
    semesterNote: "",
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
    if (!base.collapsed || typeof base.collapsed !== "object") base.collapsed = {};
    base.allHours = base.allHours === true;
    if (!base.touched || typeof base.touched !== "object") base.touched = {};
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

  function postJSON(path, body) {
    return request(path, { method: "POST", body: JSON.stringify(body || {}) });
  }

  function errorText(err) {
    if (!err) return T("app.errors.unknown", "");
    return txt(err.message) || T("app.errors.unknown", "");
  }

  /** מספרים רצים — תשובה שמגיעה אחרי בקשה חדשה יותר נזרקת. */
  var seq = { semester: 0, courses: 0, solve: 0, catalog: 0, browse: 0, electives: 0 };

  /* =====================================================================
   * 5. נגזרות מהמצב
   * ===================================================================== */

  /**
   * לוח הסמסטרים של המסלול שנבחר. ‏semesterOf() ממפה שנה+סמסטר למספר
   * סמסטר לפני כל משיכה מהשרת, ולכן הוא חייב את הלוח הנכון כבר כאן:
   * מתמטיקה שימושית היא תוכנית תלת-שנתית בת שישה סמסטרים, ולוח של שמונה
   * היה מציע לה סמסטר 7 שאינו קיים.
   * בלי לוח למסלול — הלוח הראשי, כפי שהיה קודם.
   */
  function bootSemesters() {
    if (!runtime.bootstrap) return [];
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
      return T("app.courses.alternatives.placement");
    }
    // ‏61179+61180 למי שאין פטור מפיזיקה אקדמית, 61181 למי שיש. אחד מהשניים.
    if (txt(rec.physicsTrack)) {
      return T("app.courses.alternatives.physicsTrack");
    }
    // קורס ששייך למסלול התמחות מסוים. חלק מהמחלקות מפצלות סמסטרים לפי
    // מסלול, והכלי אינו יודע באיזה מסלול הסטודנט/ית — באזרחית הוא נקבע
    // לפי ציונים. מציגים, מסבירים, ולא מסמנים.
    if (txt(rec.track)) {
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
    // הבעלות היא על צמד מסלול+סמסטר. ראו ההערה ליד ``autoProgram``.
    var sameOwner = owned === target && txt(state.autoProgram) === txt(state.program);

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
      sameCodes(next, state.codes) &&
      nextSemester === owned &&
      txt(state.autoProgram) === txt(state.program) &&
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
      autoProgram: nextSemester ? txt(state.program) : "",
      autoCodes: recommended.slice(),
      autoDropped: [],
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
      autoProgram: txt(state.program),
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
    markTouched("lecturers");
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
        var semInfo = (data && data.info) || {};
        // ‏false בלבד הוא אזהרה. ‏undefined פירושו "השרת לא אמר", וזה לא
        // אותו דבר — תוכנית שאין בה בדיקת סכום אינה תוכנית חשודה.
        runtime.semesterReconciles = semInfo.reconciles === false ? false : null;
        runtime.semesterNote = txt(semInfo.semester_note);
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
      track: txt(rec.track),
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
              (code === 0
                ? T("app.toasts.scrapeDone")
                : T("app.toasts.scrapeFailed")),
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
          txt(data.message) || T("app.scrape.reparseSummary");
        runtime.logShown = 0;
        toast(txt(data.message) || T("app.toasts.reparseDone"), "ok");
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
    if (runtime.reparseBusy) return T("app.scrape.reparseRunning");
    var sc = runtime.scrape;
    var codes = pickList(sc, ["codes"], null).map(txt).filter(Boolean);
    var total = num(sc.total, codes.length || null);

    if (sc.running === true) {
      var done = num(sc.done, null);
      if (total !== null) {
        return done !== null
          ? Tf("app.scrape.refreshingWithDone", { total: total, done: done })
          : Tf("app.scrape.refreshing", { total: total });
      }
      return T("app.scrape.refreshingNoCount");
    }

    if (txt(sc.summary)) return txt(sc.summary);
    if (sc.exit_code === null || sc.exit_code === undefined) return "";
    if (num(sc.exit_code, 1) === 0) {
      var updated = num(sc.updated, total);
      var changed = num(sc.changed, null);
      var line =
        updated === null
          ? changed === null
            ? T("app.scrape.doneNoCount")
            : Tf("app.scrape.doneNoCountWithChanges", { changed: changed })
          : changed === null
          ? Tf("app.scrape.doneUpdated", { updated: updated })
          : Tf("app.scrape.doneUpdatedWithChanges", {
              updated: updated,
              changed: changed,
            });
      return line;
    }
    return txt(sc.message) || T("app.scrape.failedSeeLog");
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
    ui.softTitle = byId("soft-conflicts-title");
    ui.softSub = byId("soft-conflicts-sub");
    ui.softList = byId("soft-conflicts-list");

    ui.themeToggle = byId("theme-toggle");
    ui.themeButtons = ui.themeToggle
      ? Array.prototype.slice.call(ui.themeToggle.querySelectorAll("[data-theme-choice]"))
      : [];

    ui.btnBuild = byId("btn-build");
    ui.progress = byId("steps-progress");
    ui.printHead = byId("print-head");
    ui.detail = byId("meeting-detail");
    ui.detailBody = byId("meeting-detail-body");
    ui.btnDetailClose = byId("btn-detail-close");
    ui.chkAllHours = byId("chk-all-hours");
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
        markTouched("year");
        // מספר הסמסטר נגזר מלוח הסמסטרים של המסלול, ולכן הוא חייב להיגזר
        // מחדש כאן. בלי זה מסלול שאין לו תוכנית כלל היה ממשיך להצהיר
        // "סמסטר 5 בתוכנית הלימודים" שנשאר מהמסלול הקודם.
        // צורת הפונקציה בכוונה: ``semesterOf`` קורא את ``state.program``,
        // ולכן הוא חייב לרוץ אחרי שהוא כבר עודכן.
        setState(function (s) {
          s.program = txt(ui.selProgram.value);
          s.semester = semesterOf(s.studyYear, s.term);
          s.activeSchedule = 0;
        });
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
        markTouched("days");
        setState({ targetDays: n, activeSchedule: 0 });
      });
    });

    if (ui.chkFriday) {
      ui.chkFriday.addEventListener("change", function () {
        markTouched("days");
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

    COLLAPSIBLE_STEPS.forEach(function (key) {
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
    if (ui.chkAllHours) {
      ui.chkAllHours.addEventListener("change", function (ev) {
        setState({ allHours: ev.target.checked === true }, { solve: false });
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
        },
        { capture: true, passive: true }
      );
    });
  }

  /**
   * רושם שסעיף נבחר בפועל.
   *
   * ‏✓ שמופיע על כל הסעיפים מהרגע הראשון אינו סימן אלא קישוט. מכאן:
   * מתאר ריק = ברירת מחדל, ‏✓ = נבחר, ‏! = יש בעיה.
   */
  function markTouched(key) {
    if (state.touched[key]) return;
    state.touched[key] = true;
    saveState();
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

  /**
   * מה שנועד למפתח/ת ולא לסטודנט/ית: כמה מערכות נמצאו, כמה זמן לקח החישוב,
   * גודל הקטלוג ושנת הלימודים. מקופל בתחתית העמוד, ונפתח מראש עם ?debug=1.
   */
  function renderTechDetails() {
    if (!ui.techFacts) return;
    if (ui.techDetails && DEBUG) ui.techDetails.open = true;
    var s = runtime.solve;
    var boot = runtime.bootstrap;
    var cat = (boot && boot.catalog) || {};
    var bits = [];
    if (s && num(s.feasible_count, null) !== null) {
      bits.push(Tf("app.tech.found", { found: num(s.feasible_count, 0) }));
      if (s.counts_truncated === true) bits.push(T("app.tech.truncated"));
    }
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
      fitBlocks(ui.overlayGrid);
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
    markTouched("year");
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

    // ‏SPEC_V2 §3: משיכת הקורסים מהידיעון אינה דורשת התחברות, ולכן זה כבר לא
    // המסלול הרגיל. הבאנר נשאר רק למקרה שהרענון רץ במסלול הדפדפן (--browser)
    // ובכל זאת דיווח שנדרשת הזדהות — שתיקה במצב כזה הייתה משאירה תקוע בלי הסבר.
    if (runtime.scrape.needs_login === true) {
      wanted.push({
        key: "needs-login",
        kind: "warn",
        text: T("app.banners.needsLogin"),
      });
    }

    if (runtime.fetchSkipped.length) {
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
    if (runtime.scrape.phase === "failed" || txt(runtime.scrapeError)) {
      var failLines = pickList(runtime.scrape, ["log"], null)
        .map(txt)
        .filter(Boolean)
        .slice(-12);
      wanted.push({
        key: "scrape-failed",
        kind: "error",
        text:
          txt(runtime.scrape.error) ||
          txt(runtime.scrapeError) ||
          T("app.toasts.scrapeFailed"),
        details: failLines.length
          ? {
              label: T("app.tech.failureDetails"),
              lines: failLines,
            }
          : null,
        action: runtime.scrape.running
          ? null
          : { label: T("app.banners.staleAction"), run: startScrape },
      });
    }

    var db = (runtime.bootstrap && runtime.bootstrap.db) || {};
    var staleCodes = uniq(pickList(db, ["stale"], null).map(txt).filter(Boolean));
    var failedSet = Object.create(null);
    uniq(pickList(db, ["failed"], null).map(txt).filter(Boolean)).forEach(function (c) {
      failedSet[c] = true;
    });
    // ‏באנר **רק** כשקורס שנבחר בפועל מושפע. מסד ישן שאף קורס נבחר אינו
    // מושפע ממנו אינו הודעה שדורשת החלטה — הוא שורת מצב, והיא כבר בכותרת.
    var staleMine = [];
    if (staleCodes.length) {
      var chosenSet = Object.create(null);
      state.codes.forEach(function (c) {
        chosenSet[txt(c)] = true;
      });
      staleMine = staleCodes.filter(function (c) {
        return chosenSet[c];
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
        action: runtime.scrape.running
          ? null
          : { label: T("app.banners.staleAction"), run: startScrape },
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
    renderProgress();
    renderStickyBar();
    renderCompare();
    renderTechDetails();
    markMissingStrings();
    // אחרי שלב 5 — הוא זה שמחשב את המערכת הפעילה, והשכבה מציגה אותה.
    renderGridOverlay();
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
      setText(ui.freshText, T("app.header.offline"));
    } else if (!boot) {
      setText(ui.freshText, T("app.header.loading"));
    } else if (!num(db.count, 0)) {
      setText(ui.freshText, T("app.header.empty"));
    } else {
      setText(
        ui.freshText,
        ageText ? Tf("app.header.fetched", { age: ageText }) : txt(db.text)
      );
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

    if (ui.btnRefresh) {
      ui.btnRefresh.disabled = runtime.scrape.running === true;
      ui.btnRefresh.textContent = runtime.scrape.running
        ? T("app.header.refreshRunning")
        : T("app.header.refreshIdle");
    }
    if (ui.btnReparse) ui.btnReparse.disabled = runtime.reparseBusy === true;

    // ‏SPEC_V2 §4: על המסך שורה אחת. השורות הגולמיות נשארות ביומן המקופל.
    var summaryLine = refreshSummaryText();
    setText(ui.refreshSummary, summaryLine);
    setHidden(ui.refreshSummary, !summaryLine);

    var sc = runtime.scrape;
    var phase =
      txt(sc.message) ||
      PHASE_HE[txt(sc.phase)] ||
      txt(sc.phase) ||
      T("app.header.phaseIdle");
    if (runtime.reparseBusy) phase = T("app.header.phaseReparse");
    if (runtime.scrapeError) {
      phase = Tf("app.header.phaseError", { error: runtime.scrapeError });
    }
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
    var yearLabel =
      YEAR_LABELS[state.studyYear] ||
      Tf("app.year.yearFallback", { year: state.studyYear });
    if (curriculumSemesterKnown()) {
      // ‏השנה והסמסטר כבר מופיעים בשורת המצב של הסעיף — שהיא גם שורת
      // הסיכום כשהוא מקופל. השבב הזה אמר בדיוק את אותו הדבר שורה מתחת,
      // ולכן הוא נושא רק את מה שאין שם: לאיזה סמסטר בתוכנית זה מתורגם,
      // וכמה קורסים מומלצים בו.
      setText(
        ui.semesterSummary,
        info && num(info.course_count, 0)
          ? Tf("app.year.summaryPlan", {
              n: txt(state.semester),
              count: info.course_count,
            })
          : Tf("app.year.summaryPlanNoCount", { n: txt(state.semester) })
      );
      setText(ui.yearNote, "");
    } else if (runtime.curriculumAvailable === false) {
      // אין תוכנית טעונה — הבחירה עצמה תקפה, ואסור לדבר על סמסטר
      // בתוכנית שאינה קיימת.
      setText(
        ui.semesterSummary,
        yearLabel + " · " + Tf("app.year.summaryTerm", { term: txt(state.term) })
      );
      setText(ui.yearNote, FALLBACK_NOTE["no-curriculum"]);
    } else {
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
    markTouched("courses");
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
        notes.push(Tf("app.courses.tiedNote", { courses: family.join(", ") }));
      });
      if (!catalogFallbackActive()) {
        notes.push(T("app.courses.addAnyNote"));
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
      state.autoCodes.length
        ? Tf("app.courses.recommended.preselected", {
            count: state.autoCodes.length,
            semester: sem,
          })
        : // קורה כשכל הסמסטר הוא חלופות — למשל סמסטר 8 בהנדסת חשמל, שכולו
          // שלושה מסלולי תכן הנדסי שבוחרים אחד מהם.
          Tf("app.courses.recommended.allElectives", { semester: sem }),
    ];
    var alternatives = runtime.semesterCourses.filter(function (rec) {
      return !!alternativeReason(rec);
    });
    if (alternatives.length) {
      var tracks = uniq(
        alternatives
          .map(function (rec) {
            return txt(rec.track);
          })
          .filter(Boolean)
      );
      parts.push(
        tracks.length
          ? Tf("app.courses.recommended.tracksNote", { tracks: tracks.join(", ") })
          : T("app.courses.recommended.alternativesNote")
      );
    }
    if (state.autoDropped.length) {
      parts.push(
        Tf("app.courses.recommended.dropped", {
          codes: state.autoDropped.join(", "),
        })
      );
    }
    parts.push(T("app.courses.recommended.catchUpHint"));
    // ‏הסתייגות, לא תקלה: מספר הנ"ז שחולץ מהשנתון אינו שווה לסה"כ שהשנתון
    // עצמו מדפיס לסמסטר הזה. לפעמים המסמך הוא שאינו מסתדר. עדיף לומר זאת
    // מאשר להציג רשימה בביטחון שאינו קיים.
    if (runtime.semesterReconciles === false) {
      parts.push(
        T("app.courses.recommended.creditsMismatch") +
          (runtime.semesterNote ? " " + runtime.semesterNote : "")
      );
    }
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
        tag: T("app.courses.status.loadingTag"),
        tagClass: "",
        text: T("app.courses.status.loadingText"),
        retry: false,
      };
    }
    if (name === "unavailable") {
      return {
        state: "unavailable",
        tag: T("app.courses.status.unavailableTag"),
        tagClass: "tag--warn",
        text: Tf("app.courses.status.unavailableText", {
          reason: reason || T("app.courses.status.unavailableReason"),
        }),
        retry: true,
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
        retry: true,
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
      tag: T("app.courses.status.pendingTag"),
      tagClass: "tag--warn",
      text: T("app.courses.status.pendingText"),
      retry: true,
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
    // ‏SPEC §3: "—" ולא "0" — 86% מהקטלוג אינו בתוכנית, ואין לו נ"ז שמורות.
    var meta = [Tf("app.courses.creditsUnit", { credits: fmtCredits(rec.credits) })];
    if (hours.length) meta.push(hours.join(" · "));
    if (rec.prereq && rec.prereq.length) {
      meta.push(Tf("app.courses.prereq", { list: rec.prereq.join(", ") }));
    }
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
          text: rec.in_curriculum
            ? T("app.courses.tags.inCurriculum")
            : T("app.courses.tags.fromCatalog"),
        })
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
    } else {
      tags.appendChild(
        el("span", {
          class: "tag tag--in-plan",
          text: Tf("app.courses.tags.inPlanSemester", { semester: txt(state.semester) }),
        })
      );
    }
    if (isTied(code)) {
      tags.appendChild(
        el("span", { class: "tag tag--tied", text: T("app.courses.tags.tied") })
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

    var cls = "course-item";
    if (checked) cls += " is-selected";
    if (isTied(code)) cls += " is-tied";
    if (unavailable) cls += " is-unavailable";

    // ‏<label> — לחיצה בכל מקום בכרטיס מחליפה את תיבת הסימון, בלי כפל אירועים.
    return el(
      "label",
      {
        class: cls,
        attrs: { title: unavailable ? T("app.courses.notOfferedTitle") : "" },
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
      isTracks ? T("app.electives.titleTracks") : T("app.electives.titleClusters")
    );
    // הכלל אינו קוסמטי: אשכול = אחד מכל קבוצה, מסלול = בוחרים מסלול אחד.
    setText(ui.electivesRule, txt(isTracks ? data.track_rule : data.cluster_rule));
    // שנה מוצגת תמיד — גם כשהמסמך לא ציין אותה, ואז נאמר בדיוק את זה.
    setText(
      ui.electivesSource,
      Tf("app.electives.source", {
        program: txt(data.program),
        year: txt(data.year_text),
      })
    );

    rebuild(ui.electivesGroups, function (box) {
      var selected = selectedSet();
      Object.keys(groups).forEach(function (name) {
        var courses = groups[name] || [];
        var wrap = el("div", { class: "electives-group" });
        wrap.appendChild(
          el("h4", {
            class: "electives-group-title",
            text: Tf("app.electives.groupTitle", {
              name: name,
              count: courses.length,
            }),
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
          ? Tf("app.days.targetImpossibleTitle", { days: n, min: minDays })
          : ""
      );
    });

    setText(ui.daysTarget, Tf("app.days.daysCount", { days: state.targetDays }));
    setText(
      ui.minDays,
      minDays === null ? "—" : Tf("app.days.daysCount", { days: minDays })
    );
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
    markTouched("lecturers");
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
    markTouched("lecturers");
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
          ]);
          missing.forEach(function (rec) {
            var line = el("div", { class: "field-row" }, [
              el("span", {
                class: "note",
                text: Tf("app.lecturers.missing.line", {
                  code: rec.code,
                  name: rec.name || nameOf(rec.code),
                  reason: rec.reason || T("app.lecturers.missing.reasonDefault"),
                }),
              }),
              retryButton(rec.code, T("app.lecturers.retry")),
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
          box.appendChild(coursePanel(course));
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
   * המשפט שמתחת למתג הכללי. הוא לא מחליף את ההסבר הקבוע שב-index.html אלא
   * מוסיף לו את המצב הנוכחי — כדי שלא ייווצר מצב שבו מתג דלוק ושום דבר לא קורה.
   */
  /**
   * השיעורים שוויתרו בהם על חובת נוכחות — כרשימה, לא כמשפט.
   * קודם היה זה זנב פסיקים של "קוד סוג" בסוף פסקה; שם קורס וסוג שיעור
   * בשורה נפרדת הם מה שאפשר באמת לסרוק בעין.
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
      box.appendChild(
        el("p", {
          class: "attendance-off-title",
          text: T("app.lecturers.attendance.offTitle"),
        })
      );
      var list = el("ul", { class: "attendance-off-list" });
      rows.forEach(function (line) {
        list.appendChild(el("li", { text: line }));
      });
      box.appendChild(list);
    });
  }

  function coursePanel(course) {
    var code = course.code;
    var idx = colorOf(code);

    var metaBits = [
      Tf("app.lecturers.meta.credits", { credits: fmtCredits(creditsOf(code)) }),
      Tf("app.lecturers.meta.groups", { count: course.groups.length }),
    ];
    var fresh = course.freshness || {};
    if (txt(fresh.age_text)) {
      // ‏"עודכן לפני 48 דקות" ולא "לפני 48 דקות": זה זמן המשיכה האחרונה
      // *של הקורס הזה*, ובלי הפועל אי אפשר לדעת של מה המספר.
      metaBits.push(Tf("app.lecturers.courseAge", { age: txt(fresh.age_text) }));
    }
    var ranked = state.ranked[code] || [];
    if (ranked.length) {
      metaBits.push(
        Tf("app.lecturers.meta.priority", {
          list: ranked
            .map(function (name, i) {
              return i + 1 + ". " + name;
            })
            .join(" · "),
        })
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
          el("th", { text: T("app.lecturers.table.group") }),
          el("th", { text: T("app.lecturers.table.kind") }),
          el("th", { text: T("app.lecturers.table.lecturer") }),
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
              title: T("app.lecturers.attendance.toggleTitle"),
            },
          },
          [input, el("span", { text: Tf("app.lecturers.attendance.label", { kind: kind }) })]
        )
      );

      var note = attendanceNoteFor(course, kind);
      if (note) {
        hints.push(Tf("app.lecturers.attendance.hint", { kind: kind, note: note }));
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
          text: Tf(
            state.allowSoftConflicts
              ? "app.lecturers.attendance.offSoft"
              : "app.lecturers.attendance.offStrict",
            { list: off.join(", ") }
          ),
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
          ? T("app.lecturers.row.pinnedTitle")
          : txt(group.lecturer)
          ? Tf(rank ? "app.lecturers.row.rankRemove" : "app.lecturers.row.rankAdd", {
              lecturer: group.lecturer,
            })
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

    // קבוצה — הקוד המלא נשאר על המסך (הוא מה שמצליבים מול הידיעון),
    // אבל תשעה מכל עשרה תווים בו זהים בין השורות. הסיפרה שמבדילה מודגשת,
    // והקידומת החוזרת מעומעמת, כדי שהעין תמצא את ההבדל במקום לספור ספרות.
    var parts = groupIdParts(gid);
    var idCell = el("td", { class: "cell-group" }, [
      el("span", { class: "gid", attrs: { title: Tf("app.lecturers.row.groupTitle", { gid: gid }) } }, [
        parts.prefix ? el("span", { class: "gid-prefix", text: parts.prefix }) : null,
        el("span", { class: "gid-suffix", text: parts.suffix }),
      ]),
    ]);
    if (group.note) {
      idCell.appendChild(el("div", { class: "course-meta", text: group.note }));
    }
    if (group.linked_to && group.linked_to.length) {
      // ‏"משויכת ל-271030210/1 ועוד 2" חזר בכל שורה כמעט ותפס עמודה שלמה.
      // סמל אחד עם תיאור אומר את אותו הדבר בלי לדחוף את הטבלה.
      var linked = group.linked_to;
      var linkedLabel = Tf(
        linked.length === 1 ? "app.lecturers.row.linkedOne" : "app.lecturers.row.linkedMany",
        { list: linked.join(", ") }
      );
      idCell.appendChild(
        el("span", {
          class: "link-badge",
          attrs: { title: linkedLabel, role: "img", "aria-label": linkedLabel },
          text: "🔗",
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
      el("span", { text: txt(group.lecturer) || T("app.lecturers.row.unknownLecturer") })
    );
    tr.appendChild(lectCell);

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

    // נעיצה — כפתור נפרד; הלחיצה עליו לא מדרגת מרצה.
    // הסמל מחליף ארבעים תוויות "נעיצה" זהות שמילאו עמודה שלמה. הוא נשאר
    // נגיש למקלדת ככפתור רגיל, ו-aria-label נושא את המשמעות המלאה — כולל
    // מספר הקבוצה, כי "נעיצה" לבדה אינה אומרת של מה.
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
      text: "📌",
      on: {
        click: function (ev) {
          ev.stopPropagation();
          if (dead) return;
          togglePin(code, kind, gid);
        },
      },
    });
    pinBtn.disabled = dead;
    // הסיבה למבוי הסתום יושבת בתיאור של השורה ושל הכפתור בלבד. כעמודה
    // משלה היא חזרה על עצמה בכל שורה חסומה והכפילה את רוחב הטבלה.
    tr.appendChild(el("td", { class: "cell-pin" }, [pinBtn]));

    return tr;
  }

  /**
   * ‏"271030210/1" -> {prefix: "271030210/", suffix: "1"}.
   * בלי סימן חוצץ הכל נחשב סיומת: עדיף להדגיש יותר מדי מאשר לנחש איפה
   * מתחיל החלק המבדיל.
   */
  function groupIdParts(gid) {
    var s = txt(gid);
    var i = s.lastIndexOf("/");
    if (i > 0 && i < s.length - 1) {
      return { prefix: s.slice(0, i + 1), suffix: s.slice(i + 1) };
    }
    return { prefix: "", suffix: s };
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
          return Tf("app.schedule.fitValue", { score: fits[i] });
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

        // ---- ההתאמה, ככותרת אחת ----
        var fits = fitScores(list);
        var idx = clamp(state.activeSchedule, 0, Math.max(0, list.length - 1));
        var fit = fits.length ? fits[idx] : 100;
        var allTied = fits.length > 1 && fits.every(function (v) {
          return v === fits[0];
        });
        // כשכל המערכות בטווח של כמה נקודות, המספר אינו מה שבוחרים לפיו —
        // התווית המבדילה היא. אז היא מובילה, והציון נסוג למשני.
        var spread = fits.length
          ? Math.max.apply(null, fits) - Math.min.apply(null, fits)
          : 0;
        var close = spread <= 5;
        var myLabel = differentiators(list)[idx] || "";
        box.appendChild(
          el("div", { class: "fit" + (close ? " fit--close" : "") }, [
            close && myLabel
              ? el("strong", { class: "fit-headline", text: myLabel })
              : null,
            el("span", { class: "fit-label", text: T("app.schedule.fitLabel") }),
            el("strong", {
              class: "fit-value ltr",
              text: Tf("app.schedule.fitValue", { score: fit }),
            }),
            el("span", {
              class: "fit-note",
              text: allTied
                ? T("app.schedule.fitTied")
                : T("app.schedule.fitTitle"),
            }),
            DEBUG
              ? el("span", {
                  class: "fit-note ltr",
                  text: Tf("app.schedule.rawScore", {
                    score: fmtNumber(sch.score),
                  }),
                })
              : null,
          ])
        );

        // ---- עובדות: מה המערכת הזאת, בלי שיפוט ----
        var factsBox = el("div", { class: "facts facts--plain" });
        factsBox.appendChild(
          fact(
            T("app.schedule.factDays"),
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
        var finish = lastFinishOf(sch);
        if (finish !== null) {
          factsBox.appendChild(fact(T("app.schedule.factFinish"), fmtTime(finish)));
        }
        factsBox.appendChild(
          fact(T("app.schedule.factGaps"), fmtDuration(sch.gap_minutes))
        );
        factsBox.appendChild(
          fact(
            T("app.schedule.factCredits"),
            creditsText(scheduleCredits(sch), { short: true })
          )
        );
        if (num(sch.lecturer_total, 0) > 0) {
          var missing = missingLecturers(sch);
          // שורה שלמה ולא שבב עם תווית: המשפט כבר מכיל את המילים
          // "מרצים מועדפים", ותווית מעליו הייתה אומרת אותן פעמיים.
          factsBox.appendChild(
            el("span", {
              class: "fact fact--wide",
              attrs: { title: T("app.score.explain.lecturer") },
              text: missing.length
                ? Tf("app.schedule.lecturersMissing", {
                    hits: num(sch.lecturer_hits, 0),
                    total: num(sch.lecturer_total, 0),
                    names: missing.join(", "),
                  })
                : Tf("app.schedule.lecturersHits", {
                    hits: num(sch.lecturer_hits, 0),
                    total: num(sch.lecturer_total, 0),
                  }),
            })
          );
        }
        box.appendChild(
          el("section", { class: "panel-block" }, [
            el("h4", {
              class: "panel-block-title",
              text: T("app.schedule.factsTitle"),
            }),
            factsBox,
          ])
        );

        // ---- מה הוריד מההתאמה: פסים, לא מספרים שליליים ----
        var penalties = penaltyList(sch).filter(function (row) {
          return !breakdownAlwaysZero(list, row.key);
        });
        var penBox = el("div", { class: "penalties" });
        if (!penalties.length) {
          penBox.appendChild(
            el("p", { class: "note", text: T("app.schedule.penaltiesNone") })
          );
        } else {
          var top = penalties[0].size || 1;
          penalties.forEach(function (row, i) {
            var label = T("app.score.breakdown." + row.key, row.key);
            var explain = T("app.score.explain." + row.key, "");
            var pct = Math.max(4, Math.round((row.size / top) * 100));
            penBox.appendChild(
              el(
                "div",
                { class: "penalty", attrs: { title: explain } },
                [
                  el("span", {
                    class: "penalty-label",
                    // ‏הגורם המשפיע ביותר נאמר במילים, לא רק באורך הפס:
                    // אורך לבדו אינו נגיש למי שלא רואה אותו.
                    text: i === 0
                      ? Tf("app.schedule.topPenalty", { label: label })
                      : label,
                  }),
                  el("span", { class: "penalty-track" }, [
                    el("span", {
                      class: "penalty-fill",
                      style: { "inline-size": pct + "%" },
                    }),
                  ]),
                ]
              )
            );
          });
        }
        box.appendChild(
          el("section", { class: "panel-block" }, [
            el("h4", {
              class: "panel-block-title",
              text: T("app.schedule.penaltiesTitle"),
            }),
            penBox,
          ])
        );
      });
    }

    // מקרא הצבעים
    if (ui.legend) {
      rebuild(ui.legend, function (box) {
        buildLegend(box, sch);
      });
    }

    // הרשת
    if (ui.grid) {
      rebuild(ui.grid, function (box) {
        if (!sch) return;
        buildGrid(box, sch, soft);
      });
      // אחרי הפריסה, לא לפניה: רק עכשיו ידוע אם הטקסט באמת נכנס.
      fitBlocks(ui.grid);
    }
    setHidden(ui.gridScroll, !sch);
    if (ui.chkAllHours) ui.chkAllHours.checked = state.allHours === true;

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
      setText(ui.scheduleNote, note);
    }
  }

  /**
   * ‏"ניקוד: -68.2". המחלקה ltr קיימת ב-style.css בדיוק בשביל זה: בלעדיה
   * המינוס של מספר שלילי מודבק בסוף ("68.2-") בגלל כיוון הכתיבה.
   */
  function fact(label, value, opts) {
    opts = opts || {};
    var node = el("span", { class: "fact", attrs: { title: txt(opts.title) } }, [
      el("span", { class: "fact-label", text: label }),
      el("strong", { class: "fact-value ltr", text: txt(value) }),
    ]);
    if (opts.hint) node.appendChild(el("span", { class: "fact-hint", text: opts.hint }));
    return node;
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
  function buildLegend(root, sch) {
    if (!sch) return;
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
      if (seen[code]) return;
      seen[code] = true;
      root.appendChild(
        el("span", {
          class: "legend-chip c" + colorOf(code),
          text: code + " " + (txt(p.name) || nameOf(code)),
        })
      );
    });
  }

  /**
   * טווח השעות של הרשת.
   *
   * ברירת המחדל היא מה שמשובץ בפועל, בתוספת חצי שעה מכל צד — יום שנגמר
   * ב-15:50 לא צריך לצייר עד 20:00. המתג "הצג את כל השעות" מחזיר את היום
   * המלא, כי יש מי שרוצה לראות גם את מה שפנוי.
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
    if (state.allHours) return { start: fullStart, end: fullEnd };

    // חצי שעה מכל צד, מיושר לחצאי שעה כדי שתוויות השעה יישארו במקומן —
    // ו**לעולם לא מעבר לטווח המלא**. בלי החסימה הזאת יום שנגמר ב-19:50
    // היה מקבל ריפוד עד 20:30, כלומר הרשת המקוצצת יוצאת גבוהה מזו של
    // "הצג את כל השעות", והמתג נראה כאילו הוא עושה את ההפך מהכתוב עליו.
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

      // ‏<button> ולא <div>: מספר הקבוצה והמרצה נמצאים רק בפאנל, ולכן
      // חייבת להיות אליו דרך במקלדת.
      var block = el(
        "button",
        {
          class: "ev c" + colorOf(m.code) + (clash ? " is-soft" : ""),
          style: style,
          attrs: { type: "button", "aria-label": label, title: label },
          data: { fk: "ev-" + key },
          on: {
            click: function () {
              // החפיפה נפתחת עם שני הצדדים, גם כשלוחצים על אחד מהם.
              openMeetingDetail(overlapPartners(m, meetings, marks), !!clash);
            },
          },
        },
        [
          // סדר הירידה קבוע, מהמוותר ביותר: מרצה, חדר, שעה. שם הקורס
          // וסוג השיעור לעולם אינם יורדים — הם מה שמזהה את הבלוק.
          el("b", { text: name }),
          el("span", { class: "ev-kind", text: txt(m.kind) }),
          el("span", {
            class: "cell-time ev-drop-2",
            text: fmtTime(from) + "–" + fmtTime(to),
          }),
          room
            ? el("span", { class: "ev-room ev-drop-1" }, [ltrCode(room)])
            : null,
          // השם המלא, ונשבר לשתי שורות אם צריך. קיצור ל"ד״ר סוקולובסקי"
          // חוסך שורה אבל מוחק בדיוק את מה שמבדיל בין שני מרצים באותו
          // שם משפחה — וזה מה שבוחרים לפיו.
          lecturer
            ? el("span", { class: "ev-lect ev-drop-3", text: lecturer })
            : null,
          clash
            ? el("span", {
                class: "ev-badge ev-drop-1",
                text: T("app.grid.clashBadge"),
              })
            : null,
        ]
      );
      root.appendChild(block);
    });
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
   * דרגות הירידה, לפי הסדר שבו הן יורדות: חדר, שעה, מרצה.
   *
   * המרצה יורד אחרון מבין השלושה. החדר הוא קוד קצר שאפשר לשלוף מהפאנל
   * או פשוט לחפש בבניין; המרצה הוא מה שבוחרים לפיו, ולכן הוא שווה יותר
   * מהשניים האחרים גם כשהמקום נגמר.
   */
  var DROP_ORDER = ["ev-drop-1", "ev-drop-2", "ev-drop-3"];

  function setDropped(block, cls, dropped) {
    var parts = block.querySelectorAll("." + cls);
    for (var j = 0; j < parts.length; j++) parts[j].hidden = dropped;
  }

  /**
   * מוריד שורות מבלוק שאין בו מקום — ורק אחרי שהפריסה כבר קרתה, כי רק
   * אז ידוע אם הטקסט באמת נכנס. שם ארוך בעמודה בחצי רוחב נשבר לשתי
   * שורות, ואי אפשר לדעת זאת מראש מתוך משך השיעור בלבד.
   *
   * הסדר קבוע: קודם החדר, אחר כך השעה. שם הקורס וסוג השיעור נשארים תמיד
   * — בלעדיהם הבלוק אינו מזהה את עצמו, וזו כל מטרתו.
   */
  function fitBlocks(root) {
    if (!root) return;
    var blocks = root.querySelectorAll(".ev");
    for (var i = 0; i < blocks.length; i++) {
      var block = blocks[i];
      // איפוס לפני מדידה. אחרת שורה שירדה בחלון צר לא הייתה חוזרת
      // כשהוא מתרחב, והמצב הקודם היה נמדד כאילו הוא הטבעי.
      for (var r = 0; r < DROP_ORDER.length; r++) {
        setDropped(block, DROP_ORDER[r], false);
      }
      for (var t = 0; t < DROP_ORDER.length; t++) {
        if (block.scrollHeight <= block.clientHeight) break;
        setDropped(block, DROP_ORDER[t], true);
      }
    }
  }

  //: ‏A4 לרוחב: הצד הקצר הוא 210 מ"מ, וזה גובה העמוד המודפס. ‏@page
  //: מכריז בדיוק על הגודל הזה, ולכן זה לא ניחוש. נייר Letter גבוה מעט
  //: יותר, כך שההנחה שמרנית.
  var PRINT_PAGE_PX = (210 * 96) / 25.4;
  var SLOT_H_PRINT = 17;
  var SLOT_H_PRINT_MIN = 12;

  /**
   * מקטין את גובה המשבצת עד שהמערכת נכנסת לעמוד אחד.
   *
   * רשת שנשפכת לעמוד שני נשברת באמצע שעה, ושורת כותרות הימים נשארת
   * מאחור — כלומר ההמשך מודפס בלי לומר איזו עמודה היא איזה יום. אין
   * דרך ב-CSS לחזור על שורת כותרות ברשת grid: ‏thead עושה זאת בטבלה,
   * ‏position: fixed אינו חוזר בעמודים נוספים ב-Chrome. לכן הפתרון אינו
   * לנהל את השבירה אלא לא להגיע אליה.
   *
   * עד 12px בלבד. מתחת לזה הבלוקים מפסידים גם את השעה, ועמוד אחד שקשה
   * לקרוא אינו שיפור על שני עמודים קריאים — ואז עדיף לוותר על ההקטנה
   * מאשר לשלם בקריאות בלי לקבל את העמוד בתמורה.
   */
  function fitGridToPage() {
    var root = document.documentElement;
    root.style.removeProperty("--slot-h");
    if (!ui.grid || !ui.grid.firstChild) return;
    if (!window.matchMedia || !window.matchMedia("print").matches) return;
    for (var h = SLOT_H_PRINT; h >= SLOT_H_PRINT_MIN; h--) {
      root.style.setProperty("--slot-h", h + "px");
      if (document.body.scrollHeight <= PRINT_PAGE_PX) return;
    }
    // לא נכנס גם במינימום — מחזירים את הגובה המלא ונותנים לו להתחלק.
    root.style.removeProperty("--slot-h");
  }

  /**
   * מודד מחדש את שתי הרשתות.
   *
   * הרוחב קובע כמה שורות נכנסות בבלוק, וההדפסה מקטינה את גובה המשבצת
   * מ-22px ל-17px — שתי הסיבות שבגללן שורה שנכנסת על המסך אינה נכנסת על
   * הנייר. בלי המדידה החוזרת החישוב היה קופא ברוחב שבו נטען הדף.
   */
  function refitBlocks() {
    // סדר: קודם גובה המשבצת (משנה את גובה כל בלוק), ורק אז מה נכנס בו.
    fitGridToPage();
    fitBlocks(ui.grid);
    fitBlocks(ui.overlayGrid);
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
    return state.touched[key] ? "chosen" : "default";
  }

  /**
   * שורת המצב שמעל הסעיפים.
   *
   * לא ממוספרת בכוונה: הסעיפים נפתחים בכל סדר, ומספור היה מבטיח רצף
   * שאינו קיים — ומרמז שסעיף שלא נגעו בו הוא משימה פתוחה, בעוד שברירת
   * המחדל היא תשובה לגיטימית לגמרי.
   */
  function renderProgress() {
    if (!ui.progress) return;
    var keys = COLLAPSIBLE_STEPS;
    var states = keys.map(sectionState);
    rebuild(ui.progress, function (box) {
      keys.forEach(function (key, i) {
        var name = T("app.steps." + key + "Title", "");
        if (!name) name = T("ui.steps." + key + "Title", key);
        var st = states[i];
        var label =
          st === "conflict"
            ? Tf("app.progress.conflict", { name: name })
            : st === "chosen"
            ? Tf("app.progress.chosen", { name: name })
            : Tf("app.progress.untouched", { name: name });
        box.appendChild(
          el("button", {
            class: "progress-chip is-" + st,
            attrs: {
              type: "button",
              title: label,
              "aria-label": Tf("app.progress.jump", { name: name }),
            },
            data: { fk: "progress-" + key },
            text: name,
            on: {
              click: function () {
                var node = ui.steps[key];
                if (!node) return;
                if (stepCollapsed(key)) {
                  state.collapsed[key] = false;
                  runtime.autoCollapsed[key] = true;
                  setState({ collapsed: state.collapsed }, { solve: false });
                }
                if (node.scrollIntoView) node.scrollIntoView({ block: "start" });
              },
            },
          })
        );
      });
      box.appendChild(
        el("span", {
          class: "progress-hint",
          text:
            states.indexOf("conflict") !== -1
              ? T("app.progress.hintConflict")
              : T("app.progress.hintDefault"),
        })
      );
    });
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
        // שנה וסמסטר בלבד. התרגום לסמסטר בתוכנית הלימודים יושב בשבב
        // שמתחת, ואמירתו כאן שוב הייתה אותה שורה פעמיים במרחק שורה.
        text: !txt(state.term)
          ? T("app.steps.year.empty")
          : Tf("app.steps.year.selected", {
              year: YEAR_LABELS[state.studyYear] || "",
              term: txt(state.term),
            }),
      },
      {
        key: "courses",
        locked: false,
        complete: hasCodes,
        text: hasCodes
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
        text: !hasCodes
          ? T("app.steps.days.waitingForCourses")
          : s && num(s.min_days, null) !== null
          ? Tf("app.steps.days.targetWithMin", {
              target: state.targetDays,
              min: s.min_days,
            })
          : Tf("app.steps.days.target", { target: state.targetDays }),
      },
      {
        key: "lecturers",
        locked: !hasData,
        complete: hasData && (rankedCount() > 0 || pinCount() > 0 || list.length > 0),
        // שני החלקים נאמרים תמיד, גם כשהם אפס: כשהשלב מקופל זו כל האמירה
        // שנשארת עליו, ו"ללא נעיצות" הוא מידע — היעדרו אינו.
        text: !hasData
          ? T("app.steps.lecturers.waitingForData")
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

  /** מדידה חוזרת בשינוי רוחב ובמעבר להדפסה. */
  function wireRefit() {
    var timer = 0;
    window.addEventListener("resize", function () {
      clearTimeout(timer);
      timer = setTimeout(refitBlocks, 120);
    });
    // ‏matchMedia ולא beforeprint: כשהאירוע הזה נורה גיליון ההדפסה כבר
    // חל, ולכן המדידה היא של הנייר. ב-beforeprint היא עדיין של המסך.
    if (!window.matchMedia) return;
    var mq = window.matchMedia("print");
    if (mq.addEventListener) mq.addEventListener("change", refitBlocks);
    else if (mq.addListener) mq.addListener(refitBlocks);
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
