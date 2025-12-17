import asyncio
import os
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    FSInputFile,
)
from aiogram.filters import Command
from database import Database

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db = Database()
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
PENDING_PHONE = set()

# Константы
WELCOME_TEXT = """Мы готовим с любовью! Ждём ваши заказы.

Все пожелания мы можем обсудить лично или по телефону: +7(985)998-91-22, +7(925)876-30-60 
Заказы принимаем по 29.12.2025 включительно!
При заказе от 20 000 руб. доставка в радиусе 15 км бесплатно"""

ABOUT_TEXT = WELCOME_TEXT
ABOUT_TEXT += "\n\nЕм&ем\nГородская ул., 20, Троицк\nhttps://yandex.ru/maps/org/yemem/42994344316?si=8qbne2jmc0nkgmphyryxvbnpq4"


def get_main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Меню", callback_data="menu")],
        [InlineKeyboardButton(text="О нас", callback_data="about")]
    ])


async def ensure_user(callback: CallbackQuery):
    """Гарантирует наличие пользователя в таблице users."""
    user = callback.from_user
    await db.get_or_create_user(user.id, user.username, user.first_name)


async def send_photo_message(message_obj, caption: str, reply_markup=None):
    photo = FSInputFile("image.png")
    return await message_obj.answer_photo(photo=photo, caption=caption, reply_markup=reply_markup)


async def edit_to_photo(message_obj, caption: str, reply_markup=None):
    photo = FSInputFile("image.png")
    media = InputMediaPhoto(media=photo, caption=caption)
    try:
        return await message_obj.edit_media(media=media, reply_markup=reply_markup)
    except Exception as e:
        logger.debug(f"edit_media failed ({e}), sending new photo message")
        return await send_photo_message(message_obj, caption, reply_markup)


def get_categories_keyboard(user_id: int = None):
    async def _get():
        categories = await db.get_categories()
        keyboard = []
        for cat in categories:
            keyboard.append([InlineKeyboardButton(
                text=cat['name'],
                callback_data=f"category_{cat['id']}"
            )])
        keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    return _get


async def get_products_keyboard(category_id: int, user_id: int):
    products = await db.get_products_by_category(category_id)
    cart_items = await db.get_cart_items(user_id)
    cart_map = {item["product_id"]: item["quantity"] for item in cart_items}
    keyboard = []
    
    for product in products:
        qty = cart_map.get(product["id"], 0)
        checkmark = "✅ " if qty > 0 else ""
        name = product['name']
        if len(name) > 25:
            name = name[:22] + "..."
        suffix = f" x{qty}" if qty > 0 else ""
        button_text = f"{checkmark}{name}{suffix} - {product['price']}₽"
        keyboard.append([InlineKeyboardButton(
            text=button_text,
            callback_data=f"product_{product['id']}"
        )])
    
    keyboard.append([InlineKeyboardButton(text="🛒 В корзину", callback_data="show_cart")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад к категориям", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def get_product_keyboard(product_id: int, user_id: int = None):
    qty = await db.get_cart_quantity(user_id, product_id) if user_id else 0
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➖", callback_data=f"dec_{product_id}"),
            InlineKeyboardButton(text=f"{qty} шт.", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{product_id}")
        ],
        [InlineKeyboardButton(text="🛒 В корзину", callback_data="show_cart")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"back_to_category")]
    ])


async def get_cart_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout")],
        [InlineKeyboardButton(text="Меню", callback_data="menu")]
    ])


async def finalize_order(user_id: int, send_func, reply_markup=None, tg_user=None):
    """Создаёт заказ, отправляет подтверждение и нотификации админам."""
    cart_items = await db.get_cart_items(user_id)
    if not cart_items:
        await send_func("Ваша корзина пуста", reply_markup=reply_markup)
        return

    total = await db.get_cart_total(user_id)
    order_id = await db.create_order(user_id)
    phone = await db.get_user_phone(user_id)
    username = getattr(tg_user, "username", None) if tg_user else None
    full_name = getattr(tg_user, "full_name", None) if tg_user else None

    text = "✅ Заказ оформлен!\n\n"
    text += f"Номер заказа: #{order_id}\n\n"
    text += "Состав заказа:\n"
    for item in cart_items:
        text += f"• {item['name']} x{item['quantity']} - {item['price'] * item['quantity']}₽\n"
    text += f"\n💰 Итого: {total}₽\n\n"
    text += "Спасибо за заказ! Мы свяжемся с вами для подтверждения."

    if reply_markup is None:
        reply_markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")]
        ])

    await send_func(text, reply_markup=reply_markup)

    # Уведомление администраторов
    if ADMIN_IDS:
        user_line = f"Пользователь: {full_name or user_id}"
        if username:
            user_line += f" (@{username})"
        user_line += f"\nТелефон: {phone or 'не указан'}"

        admin_text = (
            f"Новый заказ #{order_id}\n"
            f"{user_line}\n\n"
            f"{format_cart_text(cart_items, total)}"
        )
        for admin_id in ADMIN_IDS:
            try:
                logger.info(f"Отправка уведомления админу {admin_id} по заказу #{order_id}")
                await bot.send_message(admin_id, admin_text)
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")
    else:
        logger.info("ADMIN_IDS не заданы, уведомления админам не отправлены")


def format_cart_text(cart_items, total):
    if not cart_items:
        return "🛒 Ваша корзина пуста."
    text = "🛒 Ваша корзина:\n\n"
    for item in cart_items:
        text += f"• {item['name']} x{item['quantity']} - {item['price'] * item['quantity']}₽\n"
    text += f"\n💰 Итого: {total}₽"
    return text


async def show_cart(callback: CallbackQuery):
    user_id = callback.from_user.id
    cart_items = await db.get_cart_items(user_id)
    total = await db.get_cart_total(user_id)
    text = format_cart_text(cart_items, total)
    if cart_items:
        markup = await get_cart_keyboard()
    else:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Меню", callback_data="menu")],
            [InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")]
        ])
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


async def render_product_view(callback: CallbackQuery, product: dict, user_id: int, notify: str = None):
    product_id = product["id"]
    qty = await db.get_cart_quantity(user_id, product_id)
    checkmark = "✅ В корзине\n\n" if qty > 0 else ""

    text = f"{checkmark}🍽 {product['name']}\n"
    if product['weight']:
        text += f"К-во: {product['weight']}\n"
    text += f"Цена: {product['price']}₽\n"
    text += f"В корзине: {qty} шт."

    keyboard = await get_product_keyboard(product_id, user_id)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer(notify if notify else None)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    await db.get_or_create_user(user_id, username, first_name)
    
    await send_photo_message(
        message,
        WELCOME_TEXT,
        reply_markup=get_main_menu_keyboard()
    )


@dp.callback_query(F.data == "about")
async def callback_about(callback: CallbackQuery):
    await edit_to_photo(
        callback.message,
        ABOUT_TEXT,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "menu")
async def callback_menu(callback: CallbackQuery):
    await ensure_user(callback)
    categories = await db.get_categories()
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(
            text=cat['name'],
            callback_data=f"category_{cat['id']}"
        )])
    keyboard.append([InlineKeyboardButton(text="🛒 В корзину", callback_data="show_cart")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
    
    await callback.message.edit_text(
        "Выберите категорию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("category_"))
async def callback_category(callback: CallbackQuery):
    await ensure_user(callback)
    category_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    products = await db.get_products_by_category(category_id)
    if not products:
        await callback.answer("В этой категории пока нет товаров", show_alert=True)
        return
    
    keyboard = await get_products_keyboard(category_id, user_id)
    
    category_name = next((cat['name'] for cat in await db.get_categories() if cat['id'] == category_id), "Категория")
    
    await callback.message.edit_text(
        f"📋 {category_name}\n\nВыберите товар:",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("product_"))
async def callback_product(callback: CallbackQuery):
    await ensure_user(callback)
    product_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    product = await db.get_product(product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    
    # Сохраняем category_id для возврата назад
    dp.current_state = getattr(dp, 'current_state', {})
    dp.current_state[user_id] = {'category_id': product['category_id']}
    
    await render_product_view(callback, product, user_id)


@dp.callback_query(F.data.startswith("add_"))
async def callback_add_to_cart(callback: CallbackQuery):
    await ensure_user(callback)
    product_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    await db.add_to_cart(user_id, product_id)
    
    product = await db.get_product(product_id)
    category_id = product['category_id']
    
    # Обновляем клавиатуру товаров
    keyboard = await get_products_keyboard(category_id, user_id)
    
    category_name = next((cat['name'] for cat in await db.get_categories() if cat['id'] == category_id), "Категория")
    
    await callback.message.edit_text(
        f"📋 {category_name}\n\nВыберите товар:",
        reply_markup=keyboard
    )
    
    await callback.answer("✅ Товар добавлен в корзину", show_alert=False)


@dp.callback_query(F.data.startswith("remove_"))
async def callback_remove_from_cart(callback: CallbackQuery):
    await ensure_user(callback)
    product_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    await db.remove_from_cart(user_id, product_id)
    
    product = await db.get_product(product_id)
    category_id = product['category_id']
    
    # Обновляем клавиатуру товаров
    keyboard = await get_products_keyboard(category_id, user_id)
    
    category_name = next((cat['name'] for cat in await db.get_categories() if cat['id'] == category_id), "Категория")
    
    await callback.message.edit_text(
        f"📋 {category_name}\n\nВыберите товар:",
        reply_markup=keyboard
    )
    
    await callback.answer("❌ Товар удален из корзины", show_alert=False)


@dp.callback_query(F.data.startswith("inc_"))
async def callback_inc(callback: CallbackQuery):
    await ensure_user(callback)
    product_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id

    await db.change_cart_quantity(user_id, product_id, 1)
    product = await db.get_product(product_id)
    await render_product_view(callback, product, user_id, notify="Добавили 1 шт.")


@dp.callback_query(F.data.startswith("dec_"))
async def callback_dec(callback: CallbackQuery):
    await ensure_user(callback)
    product_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id

    await db.change_cart_quantity(user_id, product_id, -1)
    product = await db.get_product(product_id)
    await render_product_view(callback, product, user_id, notify="Убрали 1 шт.")


@dp.callback_query(F.data == "noop")
async def callback_noop(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data == "back_to_category")
async def callback_back_to_category(callback: CallbackQuery):
    await ensure_user(callback)
    user_id = callback.from_user.id
    state = getattr(dp, 'current_state', {}).get(user_id, {})
    category_id = state.get('category_id')
    
    if category_id:
        products = await db.get_products_by_category(category_id)
        if not products:
            await callback.answer("В этой категории пока нет товаров", show_alert=True)
            return
        
        keyboard = await get_products_keyboard(category_id, user_id)
        category_name = next((cat['name'] for cat in await db.get_categories() if cat['id'] == category_id), "Категория")
        
        await callback.message.edit_text(
            f"📋 {category_name}\n\nВыберите товар:",
            reply_markup=keyboard
        )
        await callback.answer()
    else:
        await callback_menu(callback)


@dp.callback_query(F.data == "checkout")
async def callback_checkout(callback: CallbackQuery):
    await ensure_user(callback)
    user_id = callback.from_user.id
    cart_items = await db.get_cart_items(user_id)
    
    if not cart_items:
        await callback.answer("Ваша корзина пуста", show_alert=True)
        return

    phone = await db.get_user_phone(user_id)
    if not phone:
        PENDING_PHONE.add(user_id)
        await callback.message.edit_text(
            "📞 Пожалуйста, отправьте номер телефона одним сообщением для оформления заказа.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")]
            ])
        )
        await callback.answer()
        return

    await finalize_order(
        user_id,
        lambda text, reply_markup=None: callback.message.edit_text(
            text,
            reply_markup=reply_markup or InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")]
            ])
        ),
        tg_user=callback.from_user
    )
    await callback.answer()


@dp.callback_query(F.data == "show_cart")
async def callback_show_cart(callback: CallbackQuery):
    await ensure_user(callback)
    await show_cart(callback)


@dp.message()
async def handle_phone_input(message: Message):
    user_id = message.from_user.id
    if user_id not in PENDING_PHONE:
        return
    phone = message.text.strip() if message.text else ""
    if len(phone) < 5:
        await message.answer("Номер слишком короткий, отправьте корректный номер.")
        return

    await db.set_user_phone(user_id, phone)
    PENDING_PHONE.discard(user_id)

    # После сохранения телефона сразу оформляем заказ
    await finalize_order(
        user_id,
        lambda text, reply_markup=None: message.answer(
            text,
            reply_markup=reply_markup or InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")]
            ])
        ),
        tg_user=message.from_user
    )


async def check_cart_on_exit(callback: CallbackQuery):
    """Проверяет корзину при выходе из меню"""
    user_id = callback.from_user.id
    cart_items = await db.get_cart_items(user_id)
    
    if cart_items:
        total = await db.get_cart_total(user_id)
        text = "🛒 Ваша корзина:\n\n"
        for item in cart_items:
            text += f"• {item['name']} x{item['quantity']} - {item['price'] * item['quantity']}₽\n"
        text += f"\n💰 Итого: {total}₽\n\n"
        text += "Оформить заказ?"
        
        keyboard = await get_cart_keyboard()
        await callback.message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    await ensure_user(callback)
    await edit_to_photo(
        callback.message,
        WELCOME_TEXT,
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()
    
    # Проверяем корзину при выходе из меню
    await check_cart_on_exit(callback)


@dp.callback_query(F.data == "show_cart")
async def callback_show_cart(callback: CallbackQuery):
    await ensure_user(callback)
    await show_cart(callback)


async def main():
    await db.connect()
    logger.info("База данных подключена")
    
    try:
        await dp.start_polling(bot)
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

