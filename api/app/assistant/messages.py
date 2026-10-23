"""Defined messages M1 to M12 and the payment refusal (SRS 0.10.2, 0.10.7, 1.7.2, 2.9.1).

These are constants. The model never writes them, paraphrases them or translates them;
code picks one by id and the language detected from the query. tests/test_messages.py
compares every string against tests/fixtures/srs_messages.yaml, which is transcribed from
the SRS tables, so a typo in either place fails CI.

M1 to M8 are the Search Assistant's (1.7.2); the Advisor reuses M2 to M8 and adds M9 to
M12 (2.9.1). PAYMENT is the Advisor's payment refusal (0.10.7); the Assistant answers a
payment request with M2, since 1.6.11 grades it OT. {max} and {n} are filled by code
(1.7.3).
"""

from typing import Literal

Lang = Literal["en", "ar"]
MessageId = Literal[
    "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10", "M11", "M12", "PAYMENT"
]

MESSAGES: dict[MessageId, dict[Lang, str]] = {
    "M1": {
        "en": "I could not find a document matching your request within your access.",
        "ar": "لم أتمكن من العثور على مستند مطابق لطلبك ضمن صلاحيات الوصول المتاحة لك.",
    },
    "M2": {
        "en": "I answer questions from company documents only.",
        "ar": "أجيب عن الأسئلة من مستندات الشركة فقط.",
    },
    "M3": {
        "en": "The assistant is temporarily unavailable. Please try again in a few minutes.",
        "ar": "المساعد غير متاح مؤقتًا. يرجى المحاولة مرة أخرى بعد بضع دقائق.",
    },
    "M4": {
        "en": "This is taking longer than expected. Please try again.",
        "ar": "يستغرق هذا وقتًا أطول من المتوقع. يرجى المحاولة مرة أخرى.",
    },
    "M5": {
        "en": "Your question is too long. Please shorten it to {max} characters or fewer.",
        "ar": "سؤالك طويل جدًا. يرجى اختصاره إلى {max} حرفًا أو أقل.",
    },
    "M6": {
        "en": "You have reached the query limit. Try again in {n} seconds.",
        "ar": "وصلت إلى الحد الأقصى للاستعلامات. حاول مرة أخرى بعد {n} ثانية.",
    },
    "M7": {
        "en": "These documents give different answers.",
        "ar": "تعطي هذه المستندات إجابات مختلفة.",
    },
    "M8": {
        "en": "This answer was written by AI from company documents. Check the quoted source before relying on it.",
        "ar": "كُتبت هذه الإجابة بواسطة الذكاء الاصطناعي من مستندات الشركة. تحقق من المصدر المقتبس قبل الاعتماد عليها.",
    },
    "M9": {
        "en": "I could not find this figure in the documents available to you.",
        "ar": "لم أتمكن من العثور على هذا الرقم في المستندات المتاحة لك.",
    },
    "M10": {
        "en": "I could not complete this calculation. Please rephrase it or provide the missing figures.",
        "ar": "لم أتمكن من إتمام هذه العملية الحسابية. يرجى إعادة الصياغة أو توفير الأرقام الناقصة.",
    },
    "M11": {
        "en": "This formula cannot be applied. Please check its terms.",
        "ar": "لا يمكن تطبيق هذه الصيغة. يرجى التحقق من عناصرها.",
    },
    "M12": {
        "en": "This calculation is not possible with these values.",
        "ar": "هذه العملية الحسابية غير ممكنة بهذه القيم.",
    },
    "PAYMENT": {
        "en": "I cannot process payments or financial transactions. This system covers operations and revenue analysis only.",
        "ar": "لا يمكنني تنفيذ المدفوعات أو المعاملات المالية. يقتصر هذا النظام على العمليات وتحليل الإيرادات.",
    },
}


def message(message_id: MessageId, lang: Lang, **placeholders: int) -> str:
    text = MESSAGES[message_id][lang]
    return text.format(**placeholders) if placeholders else text
