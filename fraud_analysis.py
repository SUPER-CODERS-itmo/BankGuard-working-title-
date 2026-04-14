import aiosqlite
import pandas as pd
import re
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Any, Union

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AmountExtractor:
    """Сервис для извлечения денежных сумм из текстовых жалоб."""

    def __init__(self):
        """Инициализирует регулярные выражения для поиска валют."""
        self.amount_pattern = re.compile(
            r'(\d+)[\s]?(?:р|руб|рублей|₽|[\.,][\s]?р)',
            re.IGNORECASE
        )
        self.loss_keyword_pattern = re.compile(
            r'пропали\s+(\d+)',
            re.IGNORECASE
        )

    def extract(self, text: Union[str, float]) -> Optional[int]:
        """
        Извлекает сумму транзакции из текста.

        Args:
            text: Входящий текст жалобы.

        Returns:
            Optional[int]: Извлеченная сумма или None, если совпадений не найдено.
        """
        if pd.isna(text):
            return None

        text_lower = str(text).lower()

        match = self.amount_pattern.search(text_lower)
        if match:
            return int(match.group(1))

        loss_match = self.loss_keyword_pattern.search(text_lower)
        if loss_match:
            return int(loss_match.group(1))

        return None


class EcosystemDB:
    """Слой доступа к данным (DAL) для работы с БД экосистемы."""

    def __init__(self, db_path: str):
        """
        Инициализирует параметры подключения.
        Само подключение происходит через менеджер контекста (with).
        """
        self.db_path = db_path
        self.conn: Optional[aiosqlite.Connection] = None

    async def __aenter__(self):
        """Открывает соединение при входе в блок async with."""
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Гарантированно закрывает соединение при выходе из блока with."""
        if self.conn:
            await self.conn.close()

    async def find_transaction_info(self, victim_id: str, amount: int) -> Optional[aiosqlite.Row]:
        """
        Ищет транзакцию в банке на основе ID жертвы и суммы.

        Args:
            victim_id: Внутренний ID пользователя в банке.
            amount: Сумма транзакции.

        Returns:
            Optional[sqlite3.Row]: Данные транзакции или None.
        """
        query = """
            SELECT 
                v.account as victim_account,
                v.phone as victim_phone,
                t.account_in as fraud_account,
                t.event_date as transaction_date,
                f.userId as fraud_bank_id,
                f.fio as fraud_fio,
                f.phone as fraud_phone
            FROM bank_clients v
            JOIN bank_transactions t ON t.account_out = v.account
            LEFT JOIN bank_clients f ON f.account = t.account_in
            WHERE v.userId = ? AND t.value = ?
            ORDER BY t.event_date DESC
            LIMIT 1
        """
        cursor = await self.conn.cursor()
        await cursor.execute(query, (victim_id, amount))
        return await cursor.fetchone()

    async def get_calls(self, victim_phone: str, fraud_phone: str) -> List[Dict[str, Any]]:
        """Получает историю звонков между жертвой и подозреваемым."""
        query = """
            SELECT 
                event_date, from_call, to_call, duration_sec
            FROM mobile_build
            WHERE (from_call = ? AND to_call = ?)
               OR (from_call = ? AND to_call = ?)
        """
        cursor = await self.conn.cursor()
        await cursor.execute(query, (victim_phone, fraud_phone, fraud_phone, victim_phone))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_market_activity(self, fraud_bank_id: int) -> List[Dict[str, Any]]:
        """Находит активность мошенника на маркетплейсе через маппинг ID."""
        query = """
            SELECT 
                md.event_date, md.contact_fio, md.contact_phone, md.address
            FROM ecosystem_mapping em
            JOIN market_place_delivery md ON md.user_id = em.marketplace_id
            WHERE em.bank_id = ?
        """
        cursor = await self.conn.cursor()
        await cursor.execute(query, (fraud_bank_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


class FraudInvestigator:
    """Оркестратор процесса расследования мошенничества."""

    def __init__(self, db_path: str, complaints_path: str, output_dir: str):
        self.db_path = db_path
        self.extractor = AmountExtractor()
        self.complaints_path = complaints_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cases = []

    async def run(self):
        """Запускает полный цикл анализа данных."""
        logger.info("Загрузка данных жалоб...")
        try:
            df = pd.read_csv(self.complaints_path, sep='\t')
        except Exception as e:
            logger.error(f"Ошибка при загрузке файла: {e}")
            return

        records = df.to_dict('records')
        logger.info(f"Обработка {len(records)} записей...")

        async with EcosystemDB(self.db_path) as db:
            for row in records:
                v_id = row.get('userId') if pd.notnull(row.get('userId')) else row.get('uerId')
                text = row.get('text')

                amount = self.extractor.extract(text)
                if not amount:
                    continue

                trans = await db.find_transaction_info(v_id, amount)
                if trans:
                    case = await self._process_fraud_case(db, v_id, text, row.get('event_date'), amount, trans)
                    self.cases.append(case)

        self._save_results()
        logger.info("Расследование завершено.")

    async def _process_fraud_case(self, db: EcosystemDB, v_id: str, text: str,
                                  date: str, amount: int, trans: aiosqlite.Row) -> Dict[str, Any]:
        """
        Обогащает данные кейса информацией из других систем (мобильная связь, маркетплейс).
        """
        case = {
            'complaint_id': v_id,
            'complaint_text': text,
            'complaint_date': date,
            'extracted_amount': amount,
            'victim_account': trans['victim_account'],
            'victim_phone': trans['victim_phone'],
            'fraud_account': trans['fraud_account'],
            'transaction_date': trans['transaction_date'],
            'fraud_bank_owner_id': trans['fraud_bank_id'],
            'fraud_bank_owner_fio': trans['fraud_fio'],
            'fraud_bank_owner_phone': trans['fraud_phone']
        }

        calls = await db.get_calls(str(case['victim_phone']), str(case['fraud_bank_owner_phone']))
        case['calls_data'] = calls
        case['has_calls'] = 1 if calls else 0

        market = await db.get_market_activity(case['fraud_bank_owner_id'])
        case['market_data'] = market
        case['has_market_activity'] = 1 if market else 0

        return case

    def _save_results(self):
        """Сохраняет результаты в CSV и готовит данные для графовой БД."""
        if not self.cases:
            logger.warning("Совпадений не найдено.")
            return

        logger.info(f"Найдено {len(self.cases)} потенциальных кейсов. Сохранение...")

        df_main = pd.DataFrame(self.cases).drop(columns=['calls_data', 'market_data'])
        df_main.to_csv(self.output_dir / "fraud_cases_detected.csv", index=False)


if __name__ == "__main__":
    investigator = FraudInvestigator(
        db_path='data/ecosystem_data.db',
        complaints_path='data/bank_complaints.tsv',
        output_dir='data/'
    )
    asyncio.run(investigator.run())
