import os
import shutil
import asyncio
import uuid
import json
import base64
import requests
import time
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, FSInputFile, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

# ==========================================
# تنظیمات توکن و آدرس پروکسی
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ مقدار BOT_TOKEN پیدا نشد! لطفا آن را در Railway تنظیم کن.")

PROXIES_URL = os.getenv("PROXIES_URL", "https://erlink.s3.ir-thr-at1.arvanstorage.ir/%DB%B6%20%288%29.txt?versionId=gʻ")

router = Router()

SESSION_BASE_DIR = "bot_sessions"
if os.path.exists(SESSION_BASE_DIR):
    shutil.rmtree(SESSION_BASE_DIR, ignore_errors=True)
os.makedirs(SESSION_BASE_DIR, exist_ok=True)

# ==========================================
# دریافت و مدیریت پروکسی‌ها
# ==========================================
PROXY_LIST = []

def load_proxies_from_url(url=PROXIES_URL):
    global PROXY_LIST
    proxies = []
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            lines = response.text.strip().splitlines()
            for line in lines:
                raw_proxy = line.strip()
                if not raw_proxy:
                    continue
                # افزودن پروتکل در صورت عدم وجود
                if not raw_proxy.startswith("http://") and not raw_proxy.startswith("https://"):
                    raw_proxy = f"http://{raw_proxy}"
                proxies.append(raw_proxy)
            print(f"✅ تعداد {len(proxies)} پروکسی از لینک بارگذاری شد.")
        else:
            print(f"❌ خطا در دریافت پروکسی: کد {response.status_code}")
    except Exception as e:
        print(f"❌ خطای اتصال در زمان دریافت لیست پروکسی: {type(e).__name__}")
    
    if proxies:
        PROXY_LIST = proxies
    return PROXY_LIST

def get_random_proxy():
    global PROXY_LIST
    if not PROXY_LIST:
        load_proxies_from_url()
    
    if not PROXY_LIST:
        return None

    selected = random.choice(PROXY_LIST)
    return {
        "http": selected,
        "https": selected
    }

def test_proxy_on_startup():
    print("🔍 [تست استارتاپ] در حال دریافت و بررسی پروکسی‌ها...")
    load_proxies_from_url()
    
    if not PROXY_LIST:
        print("❌ لیست پروکسی‌ها خالی است!")
        return False

    try:
        proxies = get_random_proxy()
        ip_used = proxies['http'].split('@')[1].split(':')[0]
        response = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=20)
        if response.status_code == 200:
            print(f"✅ ارتباط با پروکسی {ip_used} موفقیت‌آمیز بود! آی‌پی خروجی: {response.json().get('ip')}")
            return True
    except Exception as e:
        print(f"❌ خطای استارتاپ: امکان اتصال به پروکسی وجود ندارد. {type(e).__name__}")
    return False

# ==========================================
# استخراج توکن‌ها از ساختار JSON
# ==========================================
def extract_tokens_from_json_dict(data):
    access_token, refresh_token = None, None
    try:
        for cookie in data.get('cookies', []):
            if cookie.get('name') == 'tokenMS':
                access_token = cookie.get('value')
            elif cookie.get('name') == 'refresh_token':
                refresh_token = cookie.get('value')
                
        if not access_token or not refresh_token:
            for origin in data.get('origins', []):
                for item in origin.get('localStorage', []):
                    if item.get('name') == 'tokenMS':
                        access_token = item.get('value')
                    elif item.get('name') == 'refresh_token':
                        refresh_token = item.get('value')
    except Exception:
        pass
    return access_token, refresh_token

def get_tokens_from_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return extract_tokens_from_json_dict(data)
    except Exception:
        return None, None

def update_file_with_new_tokens(file_path, old_acc, new_acc, old_ref, new_ref):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        if old_acc and new_acc:
            content = content.replace(old_acc, new_acc)
        if old_ref and new_ref:
            content = content.replace(old_ref, new_ref)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception:
        pass

def get_user_id_from_token(token):
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        decoded_bytes = base64.urlsafe_b64decode(payload)
        data = json.loads(decoded_bytes)
        return data.get('cerberusId') or data.get('alternativeCustomerId')
    except Exception:
        return None

def refresh_okala_token(refresh_token, proxies):
    url = "https://apigateway.okala.com/api/v1/accounts/tokens"
    payload = {
        "grant_type": "refresh_token",
        "client_id": "customer_client_id",
        "client_secret": "u_M{'57j!%LI21#",
        "scope": "offline_access",
        "refresh_token": refresh_token
    }
    headers = {
        "content-type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/137.0.0.0 Mobile"
    }
    try:
        response = requests.post(url, data=payload, headers=headers, proxies=proxies, timeout=45)
        if response.status_code == 200:
            data = response.json()
            return data.get('access_token'), data.get('refresh_token')
    except Exception:
        pass
    return None, None

def check_single_account(token, proxies):
    user_uuid = get_user_id_from_token(token)
    if not user_uuid:
        return "error_uuid"
    
    api_url = f"https://apigateway.okala.com/api/discount/v1/discounts/customer/{user_uuid}"
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json, text/plain, */*',
        'source': 'okala',
        'ui-version': '2.0',
        'origin': 'https://www.okala.com',
        'X-Correlation-Id': str(uuid.uuid4()),
        'X-User-Unique-Id': str(uuid.uuid4()),
        'session-id': str(uuid.uuid4()),
        'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
        'sec-ch-ua-mobile': '?1',
        'sec-ch-ua-platform': '"Android"',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/137.0.0.0 Mobile'
    }
    
    try:
        response = requests.get(api_url, headers=headers, proxies=proxies, timeout=45)
        if response.status_code == 200:
            discounts = response.json().get('data', [])
            if not discounts:
                return 0
            valid_amounts = [d.get('discountAmount', 0) for d in discounts if d.get('discountAmount')]
            return max(valid_amounts) if valid_amounts else 0
        elif response.status_code == 401:
            return "expired"
        else:
            return f"error_api_{response.status_code}"
    except Exception as e:
        return f"error_net_{type(e).__name__}"

# ==========================================
# Worker فایل‌های محلی زیپ
# ==========================================
def worker_check_account(file_path, filename):
    time.sleep(random.uniform(0.1, 0.5))
    acc_token, ref_token = get_tokens_from_file(file_path)
    if not acc_token:
        return filename, file_path, "no_token"
        
    result = "error_net_init"
    for _ in range(3):
        current_proxy = get_random_proxy()
        result = check_single_account(acc_token, proxies=current_proxy)
        if "error_net" not in str(result):
            break
        time.sleep(1)
        
    if "error_net" in str(result):
        return filename, file_path, result
    
    if result == "expired" and ref_token:
        new_acc, new_ref = None, None
        for _ in range(3):
            current_proxy = get_random_proxy()
            new_acc, new_ref = refresh_okala_token(ref_token, proxies=current_proxy)
            if new_acc: break
            time.sleep(1.5)
            
        if new_acc:
            update_file_with_new_tokens(file_path, acc_token, new_acc, ref_token, new_ref)
            for _ in range(3):
                current_proxy = get_random_proxy()
                result = check_single_account(new_acc, proxies=current_proxy)
                if "error_net" not in str(result):
                    break
                time.sleep(1)
                
    return filename, file_path, result

# ==========================================
# پردازش و بررسی لینک‌ها
# ==========================================
def process_single_link(url):
    try:
        fetch_res = requests.get(url, timeout=25, proxies=get_random_proxy())
        if fetch_res.status_code != 200:
            return url, f"خطای دریافت لینک ({fetch_res.status_code})"
        
        json_data = fetch_res.json()
    except Exception as e:
        return url, f"خطا در خواندن داده: {type(e).__name__}"

    acc_token, ref_token = extract_tokens_from_json_dict(json_data)
    if not acc_token:
        return url, "توکن داخل لینک پیدا نشد"

    result = "error_net_init"
    for _ in range(3):
        current_proxy = get_random_proxy()
        result = check_single_account(acc_token, proxies=current_proxy)
        if "error_net" not in str(result):
            break
        time.sleep(1)

    if result == "expired" and ref_token:
        new_acc = None
        for _ in range(3):
            current_proxy = get_random_proxy()
            new_acc, _ = refresh_okala_token(ref_token, proxies=current_proxy)
            if new_acc:
                break
            time.sleep(1.5)
            
        if new_acc:
            for _ in range(3):
                current_proxy = get_random_proxy()
                result = check_single_account(new_acc, proxies=current_proxy)
                if "error_net" not in str(result):
                    break
                time.sleep(1)

    if isinstance(result, int):
        if result > 0:
            return url, int(result / 10000)
        return url, 0
    elif result == "expired":
        return url, "توکن منقضی شده"
    return url, str(result)

def process_links_batch(links):
    results = []
    with ThreadPoolExecutor(max_workers=min(10, len(links))) as executor:
        futures = {executor.submit(process_single_link, url): url for url in links}
        for future in as_completed(futures):
            results.append(future.result())
    return results

# ==========================================
# مدیریت فایل زیپ
# ==========================================
def process_and_categorize(extracted_dir, session_dir):
    src_accounts, src_data = None, None
    for root, dirs, _ in os.walk(extracted_dir):
        if 'accounts' in dirs and not src_accounts:
            src_accounts = os.path.join(root, 'accounts')
        if 'data' in dirs and not src_data:
            src_data = os.path.join(root, 'data')

    if not src_accounts:
        return None, None, "❌ پوشه 'accounts' داخل فایل زیپ پیدا نشد."

    categories = {}
    stats = {"total": 0, "discounts": 0, "nodiscounts": 0, "expired": 0, "errors": 0}
    
    nodiscount_path = os.path.join(session_dir, "No_Discount")
    os.makedirs(os.path.join(nodiscount_path, 'accounts'), exist_ok=True)
    os.makedirs(os.path.join(nodiscount_path, 'data'), exist_ok=True)
    if src_data and os.path.exists(os.path.join(src_data, 'accounts.json')):
        shutil.copy2(os.path.join(src_data, 'accounts.json'), os.path.join(nodiscount_path, 'data'))

    all_files = [f for f in os.listdir(src_accounts) if os.path.isfile(os.path.join(src_accounts, f))]
    stats["total"] = len(all_files)
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(worker_check_account, os.path.join(src_accounts, filename), filename): filename 
            for filename in all_files
        }
        
        for future in as_completed(futures):
            filename, file_path, result = future.result()
            
            if result == "no_token":
                shutil.copy2(file_path, os.path.join(nodiscount_path, 'accounts'))
                stats["errors"] += 1
                continue

            if isinstance(result, int) and result > 0:
                stats["discounts"] += 1
                amount_hezar_toman = int(result / 10000)
                
                cat_id = f"dl_{amount_hezar_toman}"
                if cat_id not in categories:
                    cat_path = os.path.join(session_dir, f"Discount_{amount_hezar_toman}T")
                    os.makedirs(os.path.join(cat_path, 'accounts'), exist_ok=True)
                    os.makedirs(os.path.join(cat_path, 'data'), exist_ok=True)
                    if src_data and os.path.exists(os.path.join(src_data, 'accounts.json')):
                        shutil.copy2(os.path.join(src_data, 'accounts.json'), os.path.join(cat_path, 'data'))
                    categories[cat_id] = {
                        "title": f"🎁 تخفیف {amount_hezar_toman} هزار تومانی",
                        "path": cat_path,
                        "count": 0,
                        "file_name": f"Discount_{amount_hezar_toman}T_Final"
                    }
                
                shutil.copy2(file_path, os.path.join(categories[cat_id]['path'], 'accounts'))
                categories[cat_id]['count'] += 1
            else:
                shutil.copy2(file_path, os.path.join(nodiscount_path, 'accounts'))
                if result == 0:
                    stats["nodiscounts"] += 1
                elif result == "expired":
                    stats["expired"] += 1
                else:
                    stats["errors"] += 1

    total_nodiscounts = stats["nodiscounts"] + stats["expired"] + stats["errors"]
    if total_nodiscounts > 0:
        categories["dl_nodiscount"] = {
            "title": "➖ بدون تخفیف (یا منقضی/ارور)",
            "path": nodiscount_path,
            "count": total_nodiscounts,
            "file_name": "No_Discount_Final"
        }

    return categories, stats, None

# ==========================================
# هندلرهای تلگرام
# ==========================================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "سلام! به ربات بررسی تخفیف‌ها خوش آمدید.\n\n"
        "روش‌های استفاده:\n"
        "1. ارسال فایل زیپ: بررسی پوشه accounts و ارسال فایل‌های زیپ تفکیک‌شده.\n"
        "2. ارسال لینک: ارسال یک یا چند لینک حاوی سشن جهت بررسی و دریافت گزارش متنی (Txt)."
    )

@router.message(F.text)
async def handle_links_text(message: Message):
    urls = re.findall(r'https?://[^\s]+', message.text)
    if not urls:
        await message.answer("پیامی حاوی لینک معتبر پیدا نشد. لطفاً لینک یا فایل زیپ ارسال کنید.")
        return

    wait_msg = await message.answer(f"در حال بررسی {len(urls)} لینک با پروکسی‌های فعال...")
    
    results = await asyncio.to_thread(process_links_batch, urls)
    await wait_msg.delete()

    discounted = []
    no_discount = []
    failed = []

    for url, res in results:
        if isinstance(res, int) and res > 0:
            discounted.append((url, res))
        elif res == 0:
            no_discount.append(url)
        else:
            failed.append((url, res))

    txt_lines = [
        "========================================",
        "          گزارش بررسی لینک‌ها           ",
        "========================================",
        f"تعداد کل لینک‌ها: {len(urls)}",
        f"دارای تخفیف: {len(discounted)}",
        f"بدون تخفیف: {len(no_discount)}",
        f"خطا یا منقضی: {len(failed)}",
        "----------------------------------------\n"
    ]

    if discounted:
        txt_lines.append("[لینک‌های دارای تخفیف]")
        for u, amt in discounted:
            txt_lines.append(f"{u} | تخفیف: {amt} هزار تومان")
        txt_lines.append("")

    if no_discount:
        txt_lines.append("[لینک‌های بدون تخفیف]")
        for u in no_discount:
            txt_lines.append(u)
        txt_lines.append("")

    if failed:
        txt_lines.append("[لینک‌های خطا یا منقضی]")
        for u, err in failed:
            txt_lines.append(f"{u} | وضعیت: {err}")
        txt_lines.append("")

    txt_content = "\n".join(txt_lines)
    file_bytes = txt_content.encode("utf-8")
    txt_doc = BufferedInputFile(file_bytes, filename="Discount_Results.txt")

    summary_text = (
        "بررسی لینک‌ها انجام شد.\n\n"
        f"کل لینک‌ها: {len(urls)}\n"
        f"دارای تخفیف: {len(discounted)}\n"
        f"بدون تخفیف: {len(no_discount)}\n"
        f"خطا/منقضی: {len(failed)}\n\n"
        "گزارش در قالب فایل متنی (Txt) ضمیمه شد."
    )

    await message.answer_document(document=txt_doc, caption=summary_text)

@router.message(F.document)
async def handle_zip_document(message: Message, bot: Bot, state: FSMContext):
    if not message.document.file_name.lower().endswith('.zip'):
        await message.answer("لطفاً فقط فایل زیپ (.zip) ارسال کنید.")
        return

    msg = await message.answer("در حال دانلود و استخراج فایل زیپ...")

    session_id = str(uuid.uuid4())
    session_dir = os.path.join(SESSION_BASE_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    extracted_dir = os.path.join(session_dir, "extracted")
    zip_path = os.path.join(session_dir, "uploaded.zip")
    
    file_info = await bot.get_file(message.document.file_id)
    await bot.download_file(file_info.file_path, zip_path)
    
    try:
        shutil.unpack_archive(zip_path, extracted_dir)
    except Exception:
        await msg.edit_text("فایل زیپ مشکل دارد و باز نمی‌شود.")
        shutil.rmtree(session_dir, ignore_errors=True)
        return

    await msg.edit_text("در حال بررسی موازی اکانت‌ها با پروکسی‌های فعال...")
    
    categories, stats, error_msg = await asyncio.to_thread(
        process_and_categorize, extracted_dir, session_dir
    )

    if error_msg:
        await msg.edit_text(error_msg)
        shutil.rmtree(session_dir, ignore_errors=True)
        return

    await msg.delete()

    if not categories:
        await message.answer("هیچ فایل سالمی برای بررسی پیدا نشد.")
        shutil.rmtree(session_dir, ignore_errors=True)
        return

    await message.answer("بررسی به پایان رسید. در حال ارسال فایل‌های زیپ...")

    for cat_id, info in categories.items():
        if info['count'] > 0:
            zip_path_base = os.path.join(session_dir, info["file_name"])
            final_zip_path = shutil.make_archive(zip_path_base, 'zip', info["path"])
            
            await message.answer_document(
                document=FSInputFile(final_zip_path),
                caption=f"{info['title']}\nتعداد: {info['count']} اکانت"
            )

    report_text = (
        "گزارش نهایی بررسی فایل‌ها:\n\n"
        f"کل اکانت‌ها: {stats['total']}\n"
        f"دارای تخفیف: {stats['discounts']}\n"
        f"بدون تخفیف/منقضی/خطا: {stats['nodiscounts'] + stats['expired'] + stats['errors']}\n\n"
        "حافظه موقت پاکسازی شد."
    )
    await message.answer(report_text)
    shutil.rmtree(session_dir, ignore_errors=True)

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    test_proxy_on_startup()
    
    print("🤖 Bot is up and running...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
