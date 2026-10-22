"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore } from "react";
import type { Lang } from "./types";

// Every interface string, in both languages. Defined messages (M1 to M12) are not here:
// they come from the API exactly as the server sends them.
const dictionary = {
  appName: { en: "Linearyze EMS", ar: "نظام لينيرايز لإدارة الفعاليات" },
  pocTag: { en: "Proof of concept", ar: "نموذج إثبات مفهوم" },
  assistant: { en: "Assistant", ar: "المساعد" },
  advisor: { en: "Advisor", ar: "المستشار" },
  searchPlaceholder: { en: "Search documents", ar: "ابحث في المستندات" },
  signOut: { en: "Sign out", ar: "تسجيل الخروج" },
  language: { en: "العربية", ar: "English" },
  role_management: { en: "Management", ar: "الإدارة" },
  role_employee: { en: "Employee", ar: "موظف" },
  role_admin: { en: "Admin", ar: "مسؤول النظام" },

  signInTitle: { en: "Sign in", ar: "تسجيل الدخول" },
  signInIntro: {
    en: "Three demo accounts with different permissions. The same questions give different answers depending on who asks.",
    ar: "ثلاثة حسابات تجريبية بصلاحيات مختلفة. الأسئلة نفسها تعطي إجابات مختلفة بحسب من يسأل.",
  },
  signInAs: { en: "Sign in as", ar: "الدخول باسم" },
  scope_management: { en: "All events, including confidential documents", ar: "كل الفعاليات بما فيها المستندات السرية" },
  scope_employee: {
    en: "Riyadh Design Expo 2026 only, no confidential documents",
    ar: "معرض الرياض للتصميم 2026 فقط، دون المستندات السرية",
  },
  scope_admin: { en: "User administration, no document access", ar: "إدارة المستخدمين فقط، دون الوصول إلى المستندات" },
  password: { en: "Password", ar: "كلمة المرور" },
  signInFailed: { en: "Sign-in failed. Check the email and password.", ar: "تعذّر تسجيل الدخول. تحقق من البريد وكلمة المرور." },

  askPlaceholder: { en: "Ask about documents, or ask for one", ar: "اسأل عن محتوى المستندات أو اطلب مستنداً" },
  advisorPlaceholder: {
    en: "Ask for a figure, or give a formula: profit = confirmed revenue - total cost",
    ar: "اطلب رقماً أو اكتب معادلة: الربح = الإيرادات المؤكدة - إجمالي التكاليف",
  },
  send: { en: "Send", ar: "إرسال" },
  keyHint: { en: "Enter to send · Shift+Enter for a new line", ar: "Enter للإرسال · Shift+Enter لسطر جديد" },
  working: { en: "Searching", ar: "جارٍ البحث" },
  calculating: { en: "Calculating", ar: "جارٍ الحساب" },
  tryThese: { en: "Try these", ar: "جرّب هذه" },
  debug: { en: "Debug", ar: "تفاصيل تقنية" },

  output_A: { en: "Document found", ar: "تم العثور على المستند" },
  output_B: { en: "Answer from documents", ar: "إجابة من المستندات" },
  output_C: { en: "Clarification needed", ar: "يلزم التوضيح" },
  output_D: { en: "Documents found", ar: "المستندات المطابقة" },
  output_E: { en: "Message", ar: "رسالة" },
  output_R: { en: "Result", ar: "النتيجة" },
  output_Q: { en: "More information needed", ar: "يلزم المزيد من المعلومات" },

  view: { en: "View", ar: "عرض" },
  download: { en: "Download", ar: "تنزيل" },
  received: { en: "Received", ar: "تاريخ الاستلام" },
  submitted: { en: "Submitted", ar: "تاريخ التقديم" },
  dated: { en: "Dated", ar: "التاريخ" },
  from: { en: "From", ar: "من" },
  to: { en: "To", ar: "إلى" },
  reference: { en: "Ref.", ar: "المرجع" },
  version: { en: "Version", ar: "الإصدار" },
  page: { en: "Page", ar: "صفحة" },
  sheet: { en: "Sheet", ar: "ورقة" },
  cells: { en: "Cells", ar: "الخلايا" },
  section: { en: "Section", ar: "القسم" },
  sources: { en: "Sources", ar: "المصادر" },
  conflictingValues: { en: "Values found", ar: "القيم الواردة" },
  close: { en: "Close", ar: "إغلاق" },
  citedPassage: { en: "Cited passage", ar: "المقطع المقتبس" },

  formula: { en: "Formula", ar: "المعادلة" },
  withValues: { en: "With values", ar: "بالقيم" },
  inputs: { en: "Inputs", ar: "المدخلات" },
  term: { en: "Term", ar: "البند" },
  value: { en: "Value", ar: "القيمة" },
  source: { en: "Source", ar: "المصدر" },
  source_document: { en: "Document", ar: "مستند" },
  source_query: { en: "Your message", ar: "رسالتك" },
  source_conversation: { en: "Earlier message", ar: "رسالة سابقة" },
  replaces: { en: "replaces document value", ar: "بدلاً من قيمة المستند" },
  estimate: { en: "Estimate", ar: "تقدير" },
  aiSelected: { en: "AI-selected definition", ar: "تعريف اختاره المساعد" },
  exact: { en: "Exact", ar: "القيمة الدقيقة" },
  options: { en: "Choose one", ar: "اختر أحدها" },

  adminTitle: { en: "Users and roles", ar: "المستخدمون والأدوار" },
  adminIntro: {
    en: "Admins manage accounts. They cannot use the Assistant or the Advisor, and cannot open documents (the API returns 403).",
    ar: "يدير مسؤول النظام الحسابات فقط، ولا يمكنه استخدام المساعد أو المستشار أو فتح المستندات (تعيد الواجهة البرمجية 403).",
  },
  email: { en: "Email", ar: "البريد" },
  name: { en: "Name", ar: "الاسم" },
  role: { en: "Role", ar: "الدور" },
  events: { en: "Events", ar: "الفعاليات" },
  all: { en: "All", ar: "الكل" },
  none: { en: "None", ar: "لا يوجد" },

  bytes: { en: "bytes", ar: "بايت" },
} as const;

export type Key = keyof typeof dictionary;

// The queries that show each capability, in both languages. They are the README's
// "six things to try".
export const EXAMPLES: Record<"assistant" | "advisor", { en: string; ar: string }[]> = {
  assistant: [
    {
      en: "Give me the letter from the Ministry of Exhibitions and Heritage that we received on the day we submitted the Exhibition Permit Application.",
      ar: "أعطني الخطاب الوارد من وزارة المعارض والتراث في اليوم الذي قدمنا فيه طلب تصريح المعرض",
    },
    { en: "What are the payment terms for Sadu Furnishings?", ar: "ما هي شروط الدفع مع شركة سدو للمفروشات؟" },
    { en: "What is the price of a standard booth?", ar: "كم سعر الجناح القياسي؟" },
    { en: "Give me the Board Memo - Executive Bonus Pool 2026", ar: "أعطني مذكرة مجلس الإدارة - مجمع المكافآت التنفيذية 2026" },
    { en: "Give me the Riyadh Marathon sponsorship contract", ar: "أعطني عقد رعاية ماراثون الرياض" },
    { en: "Pay the Qamar Lighting invoice today", ar: "ادفع فاتورة مؤسسة قمر للإضاءة اليوم" },
  ],
  advisor: [
    {
      en: "How many booths do we need to sell at Expo 2026 to cover organisation costs? break-even booths = (total cost − confirmed revenue) / standard booth price",
      ar: "ربح = إيرادات ناقص تكاليف. ما هو ربح معرض 2026؟",
    },
    {
      en: "For Expo 2026, assuming a standard booth price of 11,000: break-even booths = (total cost − confirmed revenue) / standard booth price",
      ar: "لمعرض 2026: صافي = إيرادات ناقص تكاليف ناقص عمولة الإعاشة",
    },
    { en: "What is the total organisation cost for Expo 2026?", ar: "ما هو إجمالي تكاليف التنظيم لمعرض 2026؟" },
  ],
};

interface LanguageContext {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: Key) => string;
}

const Context = createContext<LanguageContext | null>(null);
const STORAGE_KEY = "ems-ui-lang";

// The interface language is a per-browser preference kept in localStorage. Read through
// useSyncExternalStore so the server render (always English) and the first client render
// agree, and a change in one tab is picked up by the others.
let unstoredLang: Lang = "en"; // used when localStorage is unavailable (private mode)

function readStoredLang(): Lang {
  try {
    return localStorage.getItem(STORAGE_KEY) === "ar" ? "ar" : "en";
  } catch {
    return unstoredLang;
  }
}

function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange);
  window.addEventListener(LANG_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(LANG_EVENT, onChange);
  };
}

const LANG_EVENT = "ems-ui-lang-change";

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const lang = useSyncExternalStore(subscribe, readStoredLang, () => "en" as Lang);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      unstoredLang = next;
    }
    window.dispatchEvent(new Event(LANG_EVENT));
  }, []);

  const value = useMemo(
    () => ({ lang, setLang, t: (key: Key) => dictionary[key][lang] }),
    [lang, setLang],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useI18n(): LanguageContext {
  const value = useContext(Context);
  if (!value) throw new Error("useI18n outside LanguageProvider");
  return value;
}

/** Direction of a piece of user text, from its first strong character (SRS 1.11.11). */
export function textDirection(text: string): "rtl" | "ltr" | undefined {
  const match = text.match(/[\p{Script=Arabic}\p{Script=Hebrew}]|[A-Za-z\p{Script=Latin}]/u);
  if (!match) return undefined;
  return /[\p{Script=Arabic}\p{Script=Hebrew}]/u.test(match[0]) ? "rtl" : "ltr";
}

export function formatDate(iso: string | undefined, lang: Lang): string {
  if (!iso) return "";
  const date = new Date(`${iso}T00:00:00`);
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-SA-u-ca-gregory-nu-latn" : "en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(date);
}
