from typing import Any

from fastapi import HTTPException


DEFAULT_USER_MESSAGES = {
    "BAD_REQUEST": "درخواست نامعتبر است.",
    "VALIDATION_ERROR": "اطلاعات واردشده معتبر نیست.",
    "AUTH_REQUIRED": "برای ادامه باید وارد حساب کاربری شوید.",
    "INVALID_TOKEN": "نشست شما معتبر نیست. لطفاً دوباره وارد شوید.",
    "PERMISSION_DENIED": "شما مجوز انجام این عملیات را ندارید.",
    "NOT_FOUND": "مورد درخواستی پیدا نشد.",
    "CONFLICT": "این عملیات با وضعیت فعلی داده‌ها ناسازگار است.",
    "INTERNAL_SERVER_ERROR": "خطای داخلی سرور رخ داده است.",
    "CHAT_NOT_FOUND": "گفتگو پیدا نشد.",
    "MESSAGE_NOT_FOUND": "پیام پیدا نشد.",
    "DOCUMENT_NOT_FOUND": "سند پیدا نشد.",
    "DOCUMENT_ACCESS_DENIED": "شما به این سند دسترسی ندارید.",
    "DOCUMENT_INVALID_FILE": "فایل سند معتبر نیست.",
    "DOCUMENT_NO_ASSET_URL": "برای این سند لینک فایل وجود ندارد.",
    "ASSET_NOT_FOUND": "فایل پیدا نشد.",
    "ASSET_NOT_READY": "فایل هنوز آماده نیست.",
    "ASSET_ACCESS_DENIED": "شما به این فایل دسترسی ندارید.",
    "ASSET_INVALID_FILE_SIZE": "اندازه فایل معتبر نیست.",
    "ASSET_FILE_TOO_LARGE": "حجم فایل بیش از حد مجاز است.",
    "ASSET_CONTENT_TYPE_NOT_ALLOWED": "نوع فایل مجاز نیست.",
    "ASSET_STORAGE_OBJECT_MISSING": "فایل در فضای ذخیره‌سازی پیدا نشد.",
    "ASSET_DOWNLOAD_FAILED": "دانلود فایل از فضای ذخیره‌سازی ناموفق بود.",
    "LLM_SERVICE_UNAVAILABLE": "سرویس هوش مصنوعی فعلاً در دسترس نیست. لطفاً بعداً دوباره تلاش کنید.",
    "LLM_REQUEST_TIMEOUT": "پاسخ سرویس هوش مصنوعی بیش از حد طول کشید. لطفاً دوباره تلاش کنید.",
    "LLM_BAD_RESPONSE": "پاسخ سرویس هوش مصنوعی معتبر نبود.",
    "EMBEDDING_SERVICE_UNAVAILABLE": "سرویس پردازش برداری متن فعلاً در دسترس نیست.",
    "EMBEDDING_BAD_RESPONSE": "پاسخ سرویس پردازش برداری متن معتبر نبود.",
    "USER_HAS_NO_COMPANY": "کاربر به هیچ شرکت یا سازمانی متصل نیست.",
    "USER_NOT_FOUND": "کاربر پیدا نشد.",
    "USER_INACTIVE": "حساب کاربری شما غیرفعال شده است.",
    "PROFILE_IMAGE_NOT_FOUND": "تصویر پروفایل پیدا نشد.",
    "COMMENT_NOT_FOUND": "یادداشت پیدا نشد.",
    "COMMENT_FILE_NOT_FOUND": "فایل یادداشت پیدا نشد.",
    "MODEL_NOT_FOUND": "مدل پیدا نشد.",
    "MODEL_ALREADY_EXISTS": "این مدل قبلاً ثبت شده است.",
    "SYSTEM_TAG_NOT_FOUND": "برچسب پیدا نشد.",
    "FINANCIAL_CARD_NOT_FOUND": "کارت مالی پیدا نشد.",
    "FINANCIAL_RECEIPT_NOT_FOUND": "رسید مالی پیدا نشد.",
    "FINANCIAL_CUSTOMER_NOT_FOUND": "طرف حساب مالی پیدا نشد.",
    "ASSISTANT_INTENT_UNCLEAR": "منظور شما را دقیق متوجه نشدم. لطفاً درخواست‌تان را روشن‌تر بیان کنید.",
    "ASSISTANT_DRAFT_NOT_FOUND": "پیش‌نویس موردنظر پیدا نشد.",
    "ASSISTANT_DRAFT_NOT_PENDING": "این پیش‌نویس دیگر در وضعیت قابل‌تغییر نیست.",
    "ASSISTANT_DRAFT_INVALID": "اطلاعات پیش‌نویس کامل یا معتبر نیست.",
    "ASSISTANT_RUN_NOT_FOUND": "جلسه دستیار پیدا نشد.",
    "ASSISTANT_RATE_LIMITED": "تعداد درخواست‌های شما از حد مجاز گذشته است. لطفاً کمی بعد دوباره تلاش کنید.",
    "ASSISTANT_FILE_UNREADABLE": "خواندن محتوای فایل ضمیمه‌شده ممکن نشد.",
}


class AppException(HTTPException):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str | None = None,
        user_message: str | None = None,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ):
        self.code = code
        self.message = message or code
        self.user_message = user_message or DEFAULT_USER_MESSAGES.get(code, "خطایی رخ داده است.")
        self.details = details
        super().__init__(
            status_code=status_code,
            detail={
                "code": self.code,
                "message": self.message,
                "user_message": self.user_message,
                "details": self.details,
                "ROLE_NOT_FOUND": "نقش موردنظر پیدا نشد.",
    "ROLE_ALREADY_EXISTS": "نقشی با این نام قبلاً ثبت شده است.",
    "ROLE_IN_USE": "این نقش به کاربران فعال اختصاص داده شده و قابل تغییر نیست.",
    "SYSTEM_ROLE_PROTECTED": "نقش‌های سیستمی قابل ویرایش یا حذف نیستند.",
    "INVALID_ROLE_IDS": "شناسه نقش‌های ارسال‌شده معتبر نیست.",
    "PERMISSION_NOT_FOUND": "مجوز موردنظر پیدا نشد.",
    "PERMISSION_ALREADY_EXISTS": "مجوزی با این نام قبلاً ثبت شده است.",
    "INVALID_PERMISSION_IDS": "شناسه مجوزهای ارسال‌شده معتبر نیست.",
    "USERNAME_ALREADY_EXISTS": "نام کاربری قبلاً ثبت شده است.",
    "COMPANY_REQUIRED": "کاربر به هیچ شرکت فعالی متصل نیست.",
    "LAST_ADMIN_PROTECTED": "آخرین مدیر فعال شرکت قابل حذف یا تغییر نیست.",
    "SELF_ACTION_FORBIDDEN": "انجام این عملیات روی حساب خودتان مجاز نیست.",
},
            headers=headers,
        )
