import asyncpg
import os
from typing import Optional, List, Dict
from urllib.parse import urlparse, unquote


class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            raise ValueError("DATABASE_URL не указан в переменных окружения")
        
        # Убираем возможные пробелы и переносы строк
        database_url = database_url.strip()
        
        # Парсим строку подключения
        try:
            parsed = urlparse(database_url)
            if not parsed.scheme:
                raise ValueError("Неверный формат DATABASE_URL. Ожидается: postgresql://user:password@host:port/database")
            
            # Извлекаем компоненты
            user = unquote(parsed.username) if parsed.username else None
            password = unquote(parsed.password) if parsed.password else None
            host = parsed.hostname or 'localhost'
            port = parsed.port or 5432
            # Важно: убираем первый слэш из пути
            database = parsed.path.lstrip('/') if parsed.path else None
            
            # Логирование для отладки (без пароля)
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Подключение к БД: host={host}, port={port}, user={user}, database={database}")
            
            if not database:
                raise ValueError("Не указано имя базы данных в DATABASE_URL")
            
            if not user:
                raise ValueError("Не указано имя пользователя в DATABASE_URL")
            
            # Создаем пул с явными параметрами
            self.pool = await asyncpg.create_pool(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                min_size=1,
                max_size=10
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Ошибка подключения к БД. DATABASE_URL (без пароля): {database_url.split('@')[0] if '@' in database_url else 'скрыто'}")
            raise ValueError(f"Ошибка подключения к базе данных: {e}. Проверьте формат DATABASE_URL: postgresql://user:password@host:port/database")
        await self.create_tables()
        await self.init_data()

    async def disconnect(self):
        if self.pool:
            await self.pool.close()

    async def create_tables(self):
        async with self.pool.acquire() as conn:
            # Таблица категорий
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS categories (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    order_index INTEGER DEFAULT 0
                )
            """)

            # Таблица товаров
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
                    name VARCHAR(500) NOT NULL,
                    weight VARCHAR(100),
                    price INTEGER NOT NULL,
                    order_index INTEGER DEFAULT 0
                )
            """)

            # Таблица пользователей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    phone VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Добавляем колонку phone, если её нет
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(50)")

            # Таблица корзин
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS carts (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id)
                )
            """)

            # Таблица позиций в корзине
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS cart_items (
                    id SERIAL PRIMARY KEY,
                    cart_id INTEGER NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(cart_id, product_id)
                )
            """)

            # Таблица заказов
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    total_price INTEGER NOT NULL,
                    status VARCHAR(50) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Таблица позиций в заказе
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS order_items (
                    id SERIAL PRIMARY KEY,
                    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    quantity INTEGER NOT NULL,
                    price INTEGER NOT NULL
                )
            """)

    async def init_data(self):
        async with self.pool.acquire() as conn:
            # Проверяем, есть ли уже данные
            count = await conn.fetchval("SELECT COUNT(*) FROM categories")
            if count > 0:
                return

            # Добавляем категории и товары
            categories_data = [
                ("Закуски", [
                    ("Сырный сет: мешочки с начинкой из творожного сыра и орехов-4шт сырные шарики с оливой в кунжуте-4шт ,мандаринки из микса сыров в морковной корочке-4шт", "500гр.", 1190),
                    ("Рулеты из говяжьего языка, фаршированные твердым сыром, яйцом и чесноком 10шт", "400гр", 1400),
                    ("Рулеты из баклажанов, фаршированные сырным кремом с чесноком , орешками и зеленью-10шт.", "350 гр.", 770),
                    ("Рулеты из ветчины , фаршированные творожным сыром и пряным огурчиком-8шт", "400гр.", 1050),
                    ("Рулет волшебный куриное филе, морковь, сыр", "100гр", 160),
                    ("Рулет куриный с беконом куриное филе, перец болгарский, зелень", "100 гр.", 185),
                    ("Сливочный печеночный тортик с грибами", "650 гр.", 1150),
                    ("Брускетты с уткой /10 шт.", "10шт", 1250),
                    ("Брускетта с слабосоленой форелью /10 шт.", "10шт.", 1680),
                    ("Канапе из печеной свеклы моцареллы и корнишона", "10шт", 890),
                    ("Канапе Цезарь-10шт", "250гр.", 970),
                    ("Холодец три мяса /400 гр.", "1шт", 620),
                    ("Язык отварной", "100 гр.", 525),
                    ("Фаршмак с семгой и перепелиным яйцом /200 гр.", "1 шт.", 396),
                    ("Тигровые креветки в слоеном тесте /1 шт.", "1 шт.", 240),
                    ("Шпинатный рулет с копченой рыбой", "100 гр.", 143),
                    ("Жульен особый: свиная шея, куриная грудка, белые грибы, шампиньоны орешки и сыр тертый 50гр", "500 гр.", 890),
                    ("Шампиньоны, фаршированные мясом и сыром", "100 гр.", 185),
                ]),
                ("Основное мясное", [
                    ("Свиная рулька запеченная", "1кг", 1450),
                    ("Ребра свиные в соусе барбекю", "100гр", 230),
                    ("Утка новогодняя, фаршированная капустой или яблоками с сухофруктами /2 кг.", "1 шт.", 2900),
                    ("Утиная грудка, запечённая в апельсиновой карамели", "100гр.", 310),
                    ("Утиная ножка ,запеченная в вишнево-клюквенном соусе", "100гр.", 270),
                    ("Мясо по-французски", "100 гр.", 210),
                    ("Щеки говяжьи, тушеные в красном соусе", "100 гр.", 345),
                ]),
                ("Мясное ассорти на мангале", [
                    ("Люля-кебаб из курицы 1шт-100гр", "1шт.", 150),
                    ("Люля-кебаб из телятины1шт-100гр", "1шт", 260),
                    ("Люля-кебаб из баранины1шт-100гр", "1шт.", 271),
                    ("Шашлычок куриный на шпажке 1шт-80гр", "1шт", 158),
                    ("Куриные крылышки в соусе «Барбекю»", "100 гр.", 145),
                ]),
                ("Рыбное основное", [
                    ("Карп фаршированный", "100 гр.", 230),
                    ("Стейк из форели", "100 гр.", 398),
                    ("Форель в слоенном тесте со шпинатом сливочном соусе кедровыми орешками", "100 гр.", 290),
                    ("Кальмары по гречески", "100гр.", 199),
                ]),
                ("Гарниры", [
                    ("Картофельное пюре", "100 гр.", 81),
                    ("Картофель из печи", "100 гр.", 86),
                    ("Рататуй: перец, томаты, баклажан ,цукини 350гр", "1шт", 560),
                    ("Плов со свининой", "100 гр.", 110),
                    ("Солянка мясная с свининой и копченостями", "100 гр.", 110),
                    ("Перец фаршированный или голубцы", "100 гр.", 115),
                    ("Овощное соцветие: шампиньоны ,перец, капусты-брокколи, цветная, брюссельская  250гр", "1шт.", 360),
                ]),
                ("Салаты", [
                    ("Столичный с говядиной", "100 гр.", 135),
                    ("Оливье с курицей", "100 гр.", 120),
                    ("Оливье по- московски с колбасой и консервированным горошком", "100гр", 130),
                    ("Орландо( язык, шампиньоны, огурец маринованный, томаты ,яйцо)- тортик 650 гр", "1шт.", 960),
                    ("Цезарь с курицей 350гр", "1шт.", 550),
                    ("Гнездо тортик /600 гр. курица, грибы, яйцо, огурец, картофель пай", "1 шт.", 900),
                    ("Жареные баклажаны с помидорами и кинзой", "100 гр.", 156),
                    ("Сельдь под шубой - тортик /650 гр.", "1 шт.", 950),
                    ("С копченой курицей и ананасом - тортик /650 гр.", "1 шт.", 950),
                    ("Мимоза- тортик /650 гр. форель, сыр, яйцо, морковь, картофель", "1 шт.", 1100),
                    ("Кок -тортик /650 гр. Ассорти из подкопчённой белой и красной рыбы, сыр, крабовые палочки, рис, яйцо, креветка", "1 шт.", 970),
                    ("Листовой с креветкой  300гр айсберг, креветка, черри, йогурт", "1шт.", 550),
                    ("Кальмаровый-  тортик 600гр", "1шт", 1050),
                    ("Фермерский- тортик 650гр", "1шт", 1075),
                    ("Мимоза по-азиатски(скумбрия г\\к,сыр, картофель, пек капуста, огурец) тортик 650гр", "1шт", 890),
                ]),
                ("Полуфабрикаты", [
                    ("Манты говядина", "500гр", 650),
                    ("Манты курица", "500гр", 385),
                    ("Манты тыква", "500гр", 340),
                    ("Пельмени три мяса( свинина , говядина, курица) Шоколадный,морковный,к", "500гр", 575),
                    ("Пельмени с лосятиной", "500гр", 630),
                    ("Пельмени с форелью", "500гр", 700),
                    ("Голубцы(три мяса),перец фаршированный(три мяса)", "500гр", 540),
                    ("Котлеты из щуки", "5шт", 1000),
                    ("Котлета пожарские", "5шт", 840),
                    ("Блины с мясом", "5шт", 465),
                ]),
            ]

            for idx, (cat_name, products) in enumerate(categories_data):
                cat_id = await conn.fetchval(
                    "INSERT INTO categories (name, order_index) VALUES ($1, $2) RETURNING id",
                    cat_name, idx
                )
                for prod_idx, (prod_name, weight, price) in enumerate(products):
                    await conn.execute(
                        "INSERT INTO products (category_id, name, weight, price, order_index) VALUES ($1, $2, $3, $4, $5)",
                        cat_id, prod_name, weight, price, prod_idx
                    )

    async def get_or_create_user(self, user_id: int, username: str = None, first_name: str = None):
        async with self.pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE id = $1", user_id
            )
            if not user:
                await conn.execute(
                    "INSERT INTO users (id, username, first_name) VALUES ($1, $2, $3)",
                    user_id, username, first_name
                )
            else:
                await conn.execute(
                    "UPDATE users SET username = $1, first_name = $2 WHERE id = $3",
                    username, first_name, user_id
                )
            return user_id

    async def get_user_phone(self, user_id: int) -> Optional[str]:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT phone FROM users WHERE id = $1", user_id)

    async def set_user_phone(self, user_id: int, phone: str):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET phone = $1 WHERE id = $2", phone, user_id)

    async def get_categories(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name FROM categories ORDER BY order_index"
            )
            return [dict(row) for row in rows]

    async def get_products_by_category(self, category_id: int) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, weight, price FROM products WHERE category_id = $1 ORDER BY order_index",
                category_id
            )
            return [dict(row) for row in rows]

    async def get_product(self, product_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM products WHERE id = $1", product_id
            )
            return dict(row) if row else None

    async def get_or_create_cart(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            cart = await conn.fetchrow(
                "SELECT id FROM carts WHERE user_id = $1", user_id
            )
            if cart:
                return cart['id']
            cart_id = await conn.fetchval(
                "INSERT INTO carts (user_id) VALUES ($1) RETURNING id",
                user_id
            )
            return cart_id

    async def add_to_cart(self, user_id: int, product_id: int, quantity: int = 1):
        """Совместимость: просто увеличивает количество на quantity."""
        await self.change_cart_quantity(user_id, product_id, quantity)

    async def change_cart_quantity(self, user_id: int, product_id: int, delta: int):
        """Изменяет количество товара в корзине (delta может быть отрицательным)."""
        cart_id = await self.get_or_create_cart(user_id)
        async with self.pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT quantity FROM cart_items WHERE cart_id = $1 AND product_id = $2",
                cart_id, product_id
            )
            new_qty = delta
            if existing:
                new_qty = existing["quantity"] + delta

            if new_qty <= 0:
                await conn.execute(
                    "DELETE FROM cart_items WHERE cart_id = $1 AND product_id = $2",
                    cart_id, product_id
                )
            elif existing:
                await conn.execute(
                    "UPDATE cart_items SET quantity = $1 WHERE cart_id = $2 AND product_id = $3",
                    new_qty, cart_id, product_id
                )
            else:
                await conn.execute(
                    "INSERT INTO cart_items (cart_id, product_id, quantity) VALUES ($1, $2, $3)",
                    cart_id, product_id, new_qty
                )

    async def remove_from_cart(self, user_id: int, product_id: int):
        cart_id = await self.get_or_create_cart(user_id)
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM cart_items WHERE cart_id = $1 AND product_id = $2",
                cart_id, product_id
            )

    async def get_cart_items(self, user_id: int) -> List[Dict]:
        cart_id = await self.get_or_create_cart(user_id)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT ci.product_id, ci.quantity, p.name, p.price, p.weight
                FROM cart_items ci
                JOIN products p ON ci.product_id = p.id
                WHERE ci.cart_id = $1
            """, cart_id)
            return [dict(row) for row in rows]

    async def get_cart_quantity(self, user_id: int, product_id: int) -> int:
        """Текущее количество товара в корзине, 0 если нет."""
        cart_id = await self.get_or_create_cart(user_id)
        async with self.pool.acquire() as conn:
            qty = await conn.fetchval(
                "SELECT quantity FROM cart_items WHERE cart_id = $1 AND product_id = $2",
                cart_id, product_id
            )
            return qty or 0

    async def get_cart_total(self, user_id: int) -> int:
        items = await self.get_cart_items(user_id)
        return sum(item['price'] * item['quantity'] for item in items)

    async def is_product_in_cart(self, user_id: int, product_id: int) -> bool:
        cart_id = await self.get_or_create_cart(user_id)
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM cart_items WHERE cart_id = $1 AND product_id = $2",
                cart_id, product_id
            )
            return count > 0

    async def create_order(self, user_id: int) -> int:
        total = await self.get_cart_total(user_id)
        cart_items = await self.get_cart_items(user_id)
        
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                order_id = await conn.fetchval(
                    "INSERT INTO orders (user_id, total_price) VALUES ($1, $2) RETURNING id",
                    user_id, total
                )
                
                for item in cart_items:
                    await conn.execute(
                        "INSERT INTO order_items (order_id, product_id, quantity, price) VALUES ($1, $2, $3, $4)",
                        order_id, item['product_id'], item['quantity'], item['price']
                    )
                
                # Очищаем корзину
                cart_id = await self.get_or_create_cart(user_id)
                await conn.execute(
                    "DELETE FROM cart_items WHERE cart_id = $1",
                    cart_id
                )
                
                return order_id

