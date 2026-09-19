import os
import re
import time
import requests
from datetime import datetime


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BALE_BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BALE_BOT_TOKEN is not set")

BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"
GET_UPDATES_URL = f"{BASE_URL}/getUpdates"


# =========================================================
# HELPERS
# =========================================================

def clean(value):
    return str(value or "").strip()


def normalize_digits(text):
    """
    Convert Persian/Arabic digits to English digits.
    """
    text = str(text or "")

    translation_table = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789"
    )

    return text.translate(translation_table)


def parse_number(value):
    """
    Convert values such as:
    276
    276 م.ت
    1,276
    ۱٬۲۷۶
    to integer/float.
    """
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


# =========================================================
# SALES REPORT PARSER
# =========================================================

def parse_sales_report(text):
    """
    Parse a Bale sales report.

    Example:

    نام فروشگاه:مارلیک5
    تاریخ1405/06/01
    مبلغ کل فروش: 276
    هدف روز:_
    تعداد فاکتور:397
    وزن سبد:696
    """

    text = normalize_digits(text)

    result = {
        "store": None,
        "date": None,
        "sales": None,
        "target": None,
        "invoices": None,
        "basket_weight": None,
    }

    # -----------------------------------------------------
    # Store
    # -----------------------------------------------------

    store_match = re.search(
        r"نام\s*فروشگاه\s*[:：]?\s*(.+)",
        text,
        re.IGNORECASE
    )

    if store_match:
        result["store"] = clean(store_match.group(1))

    # -----------------------------------------------------
    # Date
    # -----------------------------------------------------

    date_match = re.search(
        r"تاریخ\s*[:：]?\s*(14\d{2}/\d{1,2}/\d{1,2})",
        text
    )

    if date_match:
        result["date"] = date_match.group(1)

    # -----------------------------------------------------
    # Total Sales
    # -----------------------------------------------------

    sales_match = re.search(
        r"مبلغ\s*کل\s*فروش\s*[:：]?\s*([^\n\r]*)",
        text,
        re.IGNORECASE
    )

    if sales_match:
        result["sales"] = parse_number(sales_match.group(1))

    # -----------------------------------------------------
    # Daily Target
    # -----------------------------------------------------

    target_match = re.search(
        r"هدف\s*روز\s*[:：]?\s*([^\n\r]*)",
        text,
        re.IGNORECASE
    )

    if target_match:
        target_value = clean(target_match.group(1))

        if target_value not in ("", "_", "-", "—"):
            result["target"] = parse_number(target_value)

    # -----------------------------------------------------
    # Invoices
    # -----------------------------------------------------

    invoice_match = re.search(
        r"تعداد\s*فاکتور\s*[:：]?\s*([^\n\r]*)",
        text,
        re.IGNORECASE
    )

    if invoice_match:
        result["invoices"] = parse_number(invoice_match.group(1))

    # -----------------------------------------------------
    # Basket Weight
    # -----------------------------------------------------

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


# =========================================================
# VALIDATION
# =========================================================

def is_sales_report(data):
    """
    A message is considered a sales report when
    the important fields exist.
    """

    required_fields = [
        data.get("store"),
        data.get("date"),
        data.get("sales"),
        data.get("invoices"),
        data.get("basket_weight"),
    ]

    return all(value is not None for value in required_fields)


# =========================================================
# DISPLAY
# =========================================================

def print_sales_report(data):
    print("\n" + "=" * 60)
    print("SALES REPORT DETECTED")
    print("=" * 60)

    print(f"Store         : {data['store']}")
    print(f"Date          : {data['date']}")
    print(f"Sales         : {data['sales']}")
    print(f"Target        : {data['target']}")
    print(f"Invoices      : {data['invoices']}")
    print(f"Basket Weight : {data['basket_weight']}")

    print("=" * 60 + "\n")


# =========================================================
# BALE API
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
    print(f"Chat Title : {chat.get('title')}")
    print(f"Sender     : {sender.get('first_name')}")
    print("Text:")
    print(text)

    # -----------------------------------------------------
    # Parse
    # -----------------------------------------------------

    report = parse_sales_report(text)

    # -----------------------------------------------------
    # Check
    # -----------------------------------------------------

    if is_sales_report(report):

        print_sales_report(report)

        print("STATUS: VALID SALES REPORT")

    else:

        print("\nSTATUS: NOT A COMPLETE SALES REPORT")

        print("\nParsed data:")
        print(report)

    print("-" * 60)


# =========================================================
# MAIN LOOP
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

            updates = result.get("result", [])

            for update in updates:

                update_id = update.get("update_id")

                if update_id is not None:
                    offset = update_id + 1

                message = update.get("message")

                if message:
                    handle_message(message)

        except KeyboardInterrupt:

            print("\nBot stopped by user.")
            break

        except Exception as e:

            print(f"MAIN LOOP ERROR: {e}")

            time.sleep(5)


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
