import sqlite3
import pandas as pd
import re
import logging
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
        # Скомпилированные паттерны работают быстрее при массовой обработке
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

        # 1. Поиск по стандартным паттернам (руб, р, ₽)
        match = self.amount_pattern.search(text_lower)
        if match:
            return int(match.group(1))

        # 2. Поиск по ключевому слову "пропали"
        loss_match = self.loss_keyword_pattern.search(text_lower)
        if loss_match:
            return int(loss_match.group(1))

        return None


class EcosystemDB:
    """Слой доступа к данным (DAL) для работы с БД экосистемы."""

    def __init__(self, db_path: str):
        """
        Устанавливает соединение с SQLite.

        Args:
            db_path: Путь к файлу базы данных.
        """
        self.conn = sqlite3.connect(db_path)
        # Позволяет обращаться к колонкам по имени
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

    def find_transaction_info(self, victim_id: int, amount: int) -> Optional[sqlite3.Row]:
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
        self.cursor.execute(query, (victim_id, amount))
        return self.cursor.fetchone()

    def get_calls(self, victim_phone: str, fraud_phone: str) -> List[Dict[str, Any]]:
        """
        Получает историю звонков между жертвой и подозреваемым.

        Args:
            victim_phone: Телефон жертвы.
            fraud_phone: Телефон мошенника.

        Returns:
            List[Dict]: Список записей о звонках.
        """
        query = """
            SELECT 
                event_date, from_call, to_call, duration_sec
            FROM mobile_build
            WHERE (from_call = ? AND to_call = ?)
               OR (from_call = ? AND to_call = ?)
        """
        self.cursor.execute(query, (victim_phone, fraud_phone, fraud_phone, victim_phone))
        return [dict(row) for row in self.cursor.fetchall()]

    def get_market_activity(self, fraud_bank_id: int) -> List[Dict[str, Any]]:
        """
        Находит активность мошенника на маркетплейсе через маппинг ID.

        Args:
            fraud_bank_id: ID мошенника в банковской системе.

        Returns:
            List[Dict]: Список доставок.
        """
        query = """
            SELECT 
                md.event_date, md.contact_fio, md.contact_phone, md.address
            FROM ecosystem_mapping em
            JOIN market_place_delivery md ON md.user_id = em.marketplace_id
            WHERE em.bank_id = ?
        """
        self.cursor.execute(query, (fraud_bank_id,))
        return [dict(row) for row in self.cursor.fetchall()]

    def close(self):
        """Закрывает соединение с БД."""
        self.conn.close()


class FraudInvestigator:
    """Оркестратор процесса расследования мошенничества."""

    def __init__(self, db_path: str, complaints_path: str, output_dir: str):
        """
        Args:
            db_path: Путь к БД.
            complaints_path: Путь к TSV файлу с жалобами.
            output_dir: Директория для сохранения результатов.
        """
        self.db = EcosystemDB(db_path)
        self.extractor = AmountExtractor()
        self.complaints_path = complaints_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cases = []

    def run(self):
        """Запускает полный цикл анализа данных."""
        logger.info("Загрузка данных жалоб...")
        try:
            df = pd.read_csv(self.complaints_path, sep='\t')
        except Exception as e:
            logger.error(f"Ошибка при загрузке файла: {e}")
            return

        logger.info(f"Обработка {len(df)} записей...")
        for _, row in df.iterrows():
            # Обработка опечатки в названии колонки (uerId -> userId)
            v_id = row.get('userId') if pd.notnull(row.get('userId')) else row.get('uerId')
            text = row['text']

            amount = self.extractor.extract(text)
            if not amount:
                continue

            trans = self.db.find_transaction_info(v_id, amount)
            if trans:
                case = self._process_fraud_case(v_id, text, row['event_date'], amount, trans)
                self.cases.append(case)

        self._save_results()
        self.db.close()
        logger.info("Расследование завершено.")

    def _process_fraud_case(self, v_id: int, text: str, date: str, amount: int, trans: sqlite3.Row) -> Dict[str, Any]:
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

        # Обогащение звонками
        calls = self.db.get_calls(case['victim_phone'], case['fraud_bank_owner_phone'])
        case['calls_data'] = calls
        case['has_calls'] = 1 if calls else 0

        # Обогащение маркетплейсом
        market = self.db.get_market_activity(case['fraud_bank_owner_id'])
        case['market_data'] = market
        case['has_market_activity'] = 1 if market else 0

        return case

    def _save_results(self):
        """Сохраняет результаты в CSV и готовит данные для графовой БД."""
        if not self.cases:
            logger.warning("Совпадений не найдено.")
            return

        logger.info(f"Найдено {len(self.cases)} потенциальных кейсов. Сохранение...")

        # Основной отчет
        df_main = pd.DataFrame(self.cases).drop(columns=['calls_data', 'market_data'])
        df_main.to_csv(self.output_dir / "fraud_cases_detected.csv", index=False)

        for case in self.cases:
            f_acc = case['fraud_account']

            if case['has_market_activity']:
                pd.DataFrame(case['market_data']).to_csv(
                    self.output_dir / f"market_activity_{f_acc}.csv", index=False
                )

            if case['has_calls']:
                pd.DataFrame(case['calls_data']).to_csv(
                    self.output_dir / f"calls_history_{f_acc}.csv", index=False
                )


if __name__ == "__main__":
    investigator = FraudInvestigator(
        db_path='data/ecosystem_data.db',
        complaints_path='data/bank_complaints.tsv',
        output_dir='data'
    )
    investigator.run()
