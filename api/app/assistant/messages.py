"""Defined messages M1 to M12 and the payment refusal (SRS 1.7.2, 2.9.1, 0.10.7).

These are constants. The model never writes them, paraphrases them or translates them;
code picks one by id and the language detected from the query. tests/test_messages.py
compares every string against tests/fixtures/srs_messages.yaml, which is transcribed from
the SRS tables, so a typo in either place fails CI.
"""

from typing import Literal

Lang = Literal["en", "ar"]
MessageId = Literal[
    "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10", "M11", "M12", "PAYMENT"
]

MESSAGES: dict[MessageId, dict[Lang, str]] = {
    "M1": {
        "en": "No information was found for this request.",
        "ar": "لم يتم العثور على معلومات لهذا الطلب.",
    },
    "M2": {
        "en": "This request is outside the scope of the assistant.",
        "ar": "هذا الطلب خارج نطاق عمل المساعد.",
    },
    "M3": {
        "en": "The service is temporarily unavailable. Please try again shortly.",
        "ar": "الخدمة غير متاحة مؤقتاً. يرجى المحاولة مرة أخرى بعد قليل.",
    },
    "M4": {
        "en": "The request took too long to complete. Please try again.",
        "ar": "استغرق الطلب وقتاً أطول من المسموح. يرجى المحاولة مرة أخرى.",
    },
    "M5": {
        "en": "The request is too long. Please shorten it and try again.",
        "ar": "الطلب طويل جداً. يرجى اختصاره والمحاولة مرة أخرى.",
    },
    "M6": {
        "en": "Too many requests. Please wait a moment before trying again.",
        "ar": "تم تجاوز عدد الطلبات المسموح به. يرجى الانتظار قليلاً ثم المحاولة مرة أخرى.",
    },
    "M7": {
        "en": "The documents contain conflicting information. Both values are shown below.",
        "ar": "تحتوي المستندات على معلومات متعارضة. تُعرض القيمتان أدناه.",
    },
    "M8": {
        "en": "This answer was generated from company documents. Verify it against the cited sources before relying on it.",
        "ar": "تم إنشاء هذه الإجابة من مستندات الشركة. يرجى التحقق منها مقابل المصادر المذكورة قبل الاعتماد عليها.",
    },
    "M9": {
        "en": "Your session has ended. Please sign in again.",
        "ar": "انتهت جلستك. يرجى تسجيل الدخول مرة أخرى.",
    },
    "M10": {
        "en": "You do not have permission to use this feature.",
        "ar": "ليست لديك صلاحية لاستخدام هذه الميزة.",
    },
    "M11": {
        "en": "The selected conversation history has been deleted.",
        "ar": "تم حذف سجل المحادثة المحدد.",
    },
    "M12": {
        "en": "The calculation cannot be completed with these values.",
        "ar": "لا يمكن إتمام العملية الحسابية بهذه القيم.",
    },
    "PAYMENT": {
        "en": "The assistant cannot make, approve or record payments or financial transactions.",
        "ar": "لا يستطيع المساعد تنفيذ المدفوعات أو اعتمادها أو تسجيلها، ولا أي معاملات مالية.",
    },
}


def message(message_id: MessageId, lang: Lang) -> str:
    return MESSAGES[message_id][lang]
