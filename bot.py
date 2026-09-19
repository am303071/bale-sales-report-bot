import os
import re
import time
import requests
import gspread
import google.auth
from datetime import datetime, timezone, timedelta

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BALE_BOT_TOKEN")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

if not BOT_TOKEN:
    raise RuntimeError("BALE_BOT_TOKEN is not set")

if not GOOGLE_SHEET_ID:
    raise RuntimeError("GOOGLE_SHEET_ID is not set")

BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"
GET_UPDATES_URL = f"{BASE_URL}/getUpdates"

IRAN_TZ = timezone(timedelta(hours=3, minutes=30))


# =========================================================
# GOOGLE SHEETS
# =========================================================

def connect_google_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials, _ = google.auth.default(scopes=scopes)
    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)

    sales_sheet = spreadsheet.worksheet("Sales_Data")
    log_sheet = spreadsheet.worksheet("Import_Log")

    print("Google Sheets connected successfully")

    return sales_sheet, log_sheet


SALES_SHEET, LOG_SHEET = connect_google_sheet()


# =========================================================
# HELPERS
# =========================================================

def clean(value):
    return str(value or "").strip()


def normalize_digits(text):
    text = str(text or "")

    translation_table = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789"
    )

    return text.translate(translation_table)


def parse_number(value):
    value = normalize_digits(value)

    value = value.replace(",", "")
    value = value.replace("٬", "")
    value = value.replace("٫", ".")

    match = re.search(r"\d+(?:\.\d+)?", value)

    if not match:
        return None

    number = match.group(0)

    if "." in number:
        return float(number)

    return int(number)


def current_datetime():
    return datetime.now(IRAN_TZ).strftime("%Y-%m-%d %H:%M:%S")


# =========================================================
# SALES REPORT PARSER
# =========================================================

def parse_sales_report(text):

    text = normalize_digits(text)

    result = {
        "store": None,
        "date": None,
        "sales": None,
        "target": None,
        "invoices": None,
        "basket_weight": None,
    }

    store_match = re.search(
        r"نام\s*فروشگاه\s*[:：]?\s*(.+)",
        text,
        re.IGNORECASE
    )

    if store_match:
        result["store"] = clean(store_match.group(1))

    date_match = re.search(
        r"تاریخ\s*[:：]?\s*(14\d{2}/\d{1,2}/\d{1,2})",
        text
    )

    if date_match:
        result["date"] = date_match.group(1)

    sales_match = re.search(
        r"مبلغ\s*کل\s*فروش\s*[:：]?\s*([^\n\r]*)",
        text,
        re.IGNORECASE
    )

    if sales_match:
        result["sales"] = parse_number(sales_match.group(1))

    target_match = re.search(
        r"هدف\s*روز\s*[:：]?\s*([^\n\r]*)",
        text,
        re.IGNORECASE
    )

    if target_match:
        target_value = clean(target_match.group(1))

        if target_value not in ("", "_", "-", "—"):
            result["target"] = parse_number(target_value)

    invoice_match = re.search(
        r"تعداد\s*فاکتور\s*[:：]?\s*([^\n\r]*)",
        text,
        re.IGNORECASE
    )

    if invoice_match:
        result["invoices"] = parse_number(invoice_match.group(1))

    basket_match = re.search(
        r"وزن\s*سبد\s*[:：]?\s*([^\n\r]*)",
        text,
        re.IGNORECASE
    )

    if basket_match:
        result["basket_weight"] = parse_number(
            basket_match.group(1)
        )

    return result


def is_sales_report(data):

    required_fields = [
        data.get("store"),
        data.get("date"),
        data.get("sales"),
        data.get("invoices"),
        data.get("basket_weight"),
    ]

    return all(value is not None for value in required_fields)


# =========================================================
# DUPLICATE CHECK
# =========================================================

def message_already_imported(message_id):

    try:
        message_ids = LOG_SHEET.col_values(1)

        return str(message_id) in [
            str(x).strip() for x in message_ids
        ]

    except Exception as e:

        print(f"DUPLICATE CHECK ERROR: {e}")

        return False


# =========================================================
# LOG
# =========================================================

def write_import_log(
    message_id,
    message_text,
    status,
    error=""
):

    try:

        LOG_SHEET.append_row(
            [
                str(message_id),
                current_datetime(),
                message_text,
                status,
                error,
                current_datetime(),
            ],
            value_input_option="USER_ENTERED"
        )

    except Exception as e:

        print(f"IMPORT LOG ERROR: {e}")


# =========================================================
# WRITE SALES DATA
# =========================================================

def save_sales_report(message_id, report):

    try:

        # If target is empty, leave the cell empty.
        target = report["target"]

        # Extract year / month / day from Persian date
        date_parts = report["date"].split("/")

        year = int(date_parts[0])
        month = int(date_parts[1])
        day = int(date_parts[2])

        row = [
            report["store"],          # A فروشگاه
            report["date"],           # B تاریخ
            report["sales"],          # C فروش
            target if target is not None else "",  # D هدف
            report["invoices"],       # E تعداد فاکتور
            report["basket_weight"],  # F وزن سبد
            year,                     # G سال
            month,                    # H ماه
            day,                      # I روز
            current_datetime(),       # J تاریخ ثبت
            "",                       # K تحقق هدف
            "",                       # L وضعیت هدف
            str(message_id),          # M Message_ID
        ]

        SALES_SHEET.append_row(
            row,
            value_input_option="USER_ENTERED"
        )

        print("Sales report saved to Google Sheets")

        return True

    except Exception as e:

        print(f"SAVE SALES ERROR: {e}")

        return False


# =========================================================
# BALE
# =========================================================

def get_updates(offset=None, timeout=30):

    params = {
        "timeout": timeout
    }

    if offset is not None:
        params["offset"] = offset

    try:

        response = requests.get(
            GET_UPDATES_URL,
            params=params,
            timeout=timeout + 10
        )

        response.raise_for_status()

        return response.json()

    except requests.exceptions.RequestException as e:

        print(f"GET UPDATES ERROR: {e}")

        return None

    except ValueError as e:

        print(f"INVALID JSON RESPONSE: {e}")

        return None


# =========================================================
# MESSAGE HANDLER
# =========================================================

def handle_message(message):

    if not message:
        return

    chat = message.get("chat", {})
    sender = message.get("from", {})

    message_id = message.get("message_id")
    text = message.get("text")

    if not text:
        return

    print("\n" + "-" * 60)
    print("NEW BALE MESSAGE")
    print("-" * 60)

    print(f"Message ID : {message_id}")
    print(f"Chat ID    : {chat.get('id')}")
    print(f"Sender     : {sender.get('first_name')}")

    print("Text:")
    print(text)

    # -----------------------------------------------------
    # DUPLICATE
    # -----------------------------------------------------

    if message_already_imported(message_id):

        print("STATUS: DUPLICATE MESSAGE - SKIPPED")

        return

    # -----------------------------------------------------
    # PARSE
    # -----------------------------------------------------

    report = parse_sales_report(text)

    if not is_sales_report(report):

        print("STATUS: NOT A COMPLETE SALES REPORT")

        write_import_log(
            message_id,
            text,
            "ردیابی نشد",
            "گزارش فروش کامل تشخیص داده نشد"
        )

        return

    # -----------------------------------------------------
    # SAVE
    # -----------------------------------------------------

    success = save_sales_report(
        message_id,
        report
    )

    if success:

        write_import_log(
            message_id,
            text,
            "ثبت شد",
            ""
        )

        print("STATUS: SAVED SUCCESSFULLY")

        print("\nParsed data:")
        print(report)

    else:

        write_import_log(
            message_id,
            text,
            "خطا",
            "خطا در ثبت اطلاعات Sales_Data"
        )

        print("STATUS: SAVE ERROR")

    print("-" * 60)


# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 60)
    print("BALE SALES REPORT BOT")
    print("=" * 60)

    print("Bot is starting...")
    print("Waiting for Bale messages...")
    print()

    offset = None

    while True:

        try:

            result = get_updates(
                offset=offset,
                timeout=30
            )

            if not result:

                time.sleep(2)
                continue

            if not result.get("ok"):

                print("BALE API ERROR:")
                print(result)

                time.sleep(5)
                continue

            updates = result.get(
                "result",
                []
            )

            for update in updates:

                update_id = update.get(
                    "update_id"
                )

                if update_id is not None:

                    offset = update_id + 1

                message = update.get(
                    "message"
                )

                if message:

                    handle_message(message)

        except KeyboardInterrupt:

            print("\nBot stopped by user.")

            break

        except Exception as e:

            print(
                f"MAIN LOOP ERROR: {e}"
            )

            time.sleep(5)


if __name__ == "__main__":
    main()
