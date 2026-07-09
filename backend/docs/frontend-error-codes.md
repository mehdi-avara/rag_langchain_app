# Porsa Frontend Error Codes

Backend API errors follow this standard shape:

    {
      "error": {
        "code": "ERROR_CODE",
        "message": "Technical message",
        "user_message": "پیام قابل نمایش به کاربر",
        "details": null,
        "request_id": null
      }
    }

Frontend should use `error.code` as the main decision key.

## Recommended frontend handling

| Code | Suggested UI behavior | Suggested Persian message |
|---|---|---|
| AUTH_REQUIRED | Redirect to login or show login modal | برای ادامه باید وارد حساب کاربری شوید. |
| INVALID_TOKEN | Clear token and redirect to login | نشست شما معتبر نیست. لطفاً دوباره وارد شوید. |
| PERMISSION_DENIED | Show warning toast/page | شما مجوز انجام این عملیات را ندارید. |
| VALIDATION_ERROR | Show field errors if possible | اطلاعات واردشده معتبر نیست. |
| BAD_REQUEST | Show error toast | درخواست نامعتبر است. |
| NOT_FOUND | Show not-found message | مورد درخواستی پیدا نشد. |
| CONFLICT | Show conflict warning | این عملیات با وضعیت فعلی داده‌ها ناسازگار است. |
| INTERNAL_SERVER_ERROR | Show generic server error | خطای داخلی سرور رخ داده است. |

## Document errors

| Code | Suggested UI behavior | Suggested Persian message |
|---|---|---|
| DOCUMENT_NOT_FOUND | Show document not found | سند پیدا نشد. |
| DOCUMENT_ACCESS_DENIED | Hide action or show access denied | شما به این سند دسترسی ندارید. |
| DOCUMENT_INVALID_FILE | Show upload validation error | فایل سند معتبر نیست. |
| DOCUMENT_NO_ASSET_URL | Disable download/preview | برای این سند لینک فایل وجود ندارد. |

## Asset/file errors

| Code | Suggested UI behavior | Suggested Persian message |
|---|---|---|
| ASSET_NOT_FOUND | Show file not found | فایل پیدا نشد. |
| ASSET_NOT_READY | Show retry/pending state | فایل هنوز آماده نیست. |
| ASSET_ACCESS_DENIED | Show access denied | شما به این فایل دسترسی ندارید. |
| ASSET_INVALID_FILE_SIZE | Show upload validation error | اندازه فایل معتبر نیست. |
| ASSET_FILE_TOO_LARGE | Show upload validation error | حجم فایل بیش از حد مجاز است. |
| ASSET_CONTENT_TYPE_NOT_ALLOWED | Show upload validation error | نوع فایل مجاز نیست. |
| ASSET_STORAGE_OBJECT_MISSING | Show storage error | فایل در فضای ذخیره‌سازی پیدا نشد. |
| ASSET_DOWNLOAD_FAILED | Show retry button | دانلود فایل ناموفق بود. |

## AI/LLM errors

| Code | Suggested UI behavior | Suggested Persian message |
|---|---|---|
| LLM_SERVICE_UNAVAILABLE | Show retry button and non-blocking AI unavailable state | سرویس هوش مصنوعی فعلاً در دسترس نیست. لطفاً بعداً دوباره تلاش کنید. |
| LLM_REQUEST_TIMEOUT | Show retry button | پاسخ سرویس هوش مصنوعی بیش از حد طول کشید. لطفاً دوباره تلاش کنید. |
| LLM_BAD_RESPONSE | Show generic AI error | پاسخ سرویس هوش مصنوعی معتبر نبود. |

## Embedding/search errors

| Code | Suggested UI behavior | Suggested Persian message |
|---|---|---|
| EMBEDDING_SERVICE_UNAVAILABLE | Show semantic search unavailable; optionally fallback to keyword search | سرویس پردازش برداری متن فعلاً در دسترس نیست. |
| EMBEDDING_BAD_RESPONSE | Show semantic search error | پاسخ سرویس پردازش برداری متن معتبر نبود. |

## User/profile errors

| Code | Suggested UI behavior | Suggested Persian message |
|---|---|---|
| USER_HAS_NO_COMPANY | Show account setup/support message | کاربر به هیچ شرکت یا سازمانی متصل نیست. |
| USER_NOT_FOUND | Show not-found message | کاربر پیدا نشد. |
| PROFILE_IMAGE_NOT_FOUND | Show default avatar | تصویر پروفایل پیدا نشد. |

## Comment errors

| Code | Suggested UI behavior | Suggested Persian message |
|---|---|---|
| COMMENT_NOT_FOUND | Show not-found message | یادداشت پیدا نشد. |
| COMMENT_FILE_NOT_FOUND | Show file not found | فایل یادداشت پیدا نشد. |

## Model/tag errors

| Code | Suggested UI behavior | Suggested Persian message |
|---|---|---|
| MODEL_NOT_FOUND | Show not-found message | مدل پیدا نشد. |
| MODEL_ALREADY_EXISTS | Show duplicate warning | این مدل قبلاً ثبت شده است. |
| SYSTEM_TAG_NOT_FOUND | Show not-found message | برچسب پیدا نشد. |

## Financial errors

| Code | Suggested UI behavior | Suggested Persian message |
|---|---|---|
| FINANCIAL_CARD_NOT_FOUND | Show not-found message | کارت مالی پیدا نشد. |
| FINANCIAL_RECEIPT_NOT_FOUND | Show not-found message | رسید مالی پیدا نشد. |
| FINANCIAL_CUSTOMER_NOT_FOUND | Show not-found message | طرف حساب مالی پیدا نشد. |

## Frontend example

Example JavaScript helper:

    export function getErrorMessage(error) {
      const code = error?.response?.data?.error?.code;
      const userMessage = error?.response?.data?.error?.user_message;

      if (userMessage) return userMessage;

      switch (code) {
        case "AUTH_REQUIRED":
        case "INVALID_TOKEN":
          return "برای ادامه باید وارد حساب کاربری شوید.";
        case "PERMISSION_DENIED":
          return "شما مجوز انجام این عملیات را ندارید.";
        case "LLM_SERVICE_UNAVAILABLE":
          return "سرویس هوش مصنوعی فعلاً در دسترس نیست. لطفاً بعداً دوباره تلاش کنید.";
        case "EMBEDDING_SERVICE_UNAVAILABLE":
          return "سرویس جستجوی معنایی فعلاً در دسترس نیست.";
        default:
          return "خطایی رخ داده است.";
      }
    }

## Notes

- Do not parse `message`; it is technical and may change.
- Prefer `user_message` for direct display.
- Use `code` for logic, routing, retry behavior, and special UI states.
- Use `request_id` for support/debugging when available.
- Keep validation errors connected to form fields when `details` contains field-level data.
