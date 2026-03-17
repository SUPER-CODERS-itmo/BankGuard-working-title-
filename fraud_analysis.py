import sqlite3
import pandas as pd
import re
import os


class AmountExtractor:
    def __init__(self):
        self.patterns = [
            r'(\d+)[\s]?р',
            r'(\d+)[\s]?руб',
            r'(\d+)[\s]?рублей',
            r'(\d+)[\s]?₽',
            r'(\d+)[\s]?[\.,]?[\s]?р',
        ]

    def extract(self, text):
        text_lower = str(text).lower()
        for pattern in self.patterns:
            match = re.search(pattern, text_lower)
            if match:
                return int(match.group(1))

        if 'пропали' in text_lower:
            words = text_lower.split()
            for i, word in enumerate(words):
                if word == 'пропали' and i + 1 < len(words):
                    numbers = re.findall(r'\d+', words[i + 1])
                    if numbers:
                        return int(numbers[0])
        return None


class EcosystemDB:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()

    def find_transaction_info(self, victim_id, amount):
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
            LIMIT 1
        """
        self.cursor.execute(query, (victim_id, amount))
        return self.cursor.fetchone()

    def get_calls(self, victim_phone, fraud_account):
        query = """
            SELECT 
                mb.event_date, mb.from_call, mb.to_call, mb.duration_sec,
                mc.phone as fraud_phone, mc.client_id as fraud_mobile_id, mc.fio as fraud_fio
            FROM bank_clients bc
            JOIN ecosystem_mapping em ON em.bank_id = bc.userId
            JOIN mobile_clients mc ON mc.client_id = em.mobile_id
            JOIN mobile_build mb ON 
                (mb.from_call = mc.phone AND mb.to_call = ?) OR 
                (mb.from_call = ? AND mb.to_call = mc.phone)
            WHERE bc.account = ?
        """
        self.cursor.execute(query, (victim_phone, victim_phone, fraud_account))
        columns = [col[0] for col in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def get_market_activity(self, fraud_account):
        query = """
            SELECT 
                md.event_date, md.user_id as fraud_market_id, md.contact_fio, md.contact_phone, md.address,
                bc.userId as fraud_bank_id
            FROM bank_clients bc
            JOIN ecosystem_mapping em ON em.bank_id = bc.userId
            JOIN market_place_delivery md ON md.user_id = em.marketplace_id
            WHERE bc.account = ?
        """
        self.cursor.execute(query, (fraud_account,))
        columns = [col[0] for col in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def close(self):
        self.conn.close()


class FraudInvestigator:
    def __init__(self, db_path, complaints_path, output_path):
        self.db = EcosystemDB(db_path)
        self.extractor = AmountExtractor()
        self.complaints_path = complaints_path
        self.output_path = output_path
        self.cases = []

    def run(self):
        print("Загрузка данных...")
        complaints_df = pd.read_csv(self.complaints_path, sep='\t')

        print("Анализ транзакций...")
        for _, row in complaints_df.iterrows():
            victim_id = row.get('uerId', row.get('userId'))
            text = row['text']
            date = row['event_date']

            amount = self.extractor.extract(text)
            if not amount:
                continue

            trans_data = self.db.find_transaction_info(victim_id, amount)
            if trans_data:
                case = self._build_case_dict(victim_id, text, date, amount, trans_data)

                calls = self.db.get_calls(case['victim_phone'], case['fraud_account'])
                case['calls_data'] = calls
                case['has_calls'] = 1 if calls else 0

                market = self.db.get_market_activity(case['fraud_account'])
                case['market_data'] = market
                case['has_market_activity'] = 1 if market else 0
                case['market_deliveries_count'] = len(market)

                self.cases.append(case)

        self.db.close()
        self._save_results()

    def _build_case_dict(self, v_id, text, date, amount, row):
        return {
            'complaint_id': v_id,
            'complaint_text': text,
            'complaint_date': date,
            'extracted_amount': amount,
            'victim_account': row[0],
            'victim_phone': row[1],
            'fraud_account': row[2],
            'transaction_date': row[3],
            'fraud_bank_owner_id': row[4],
            'fraud_bank_owner_fio': row[5],
            'fraud_bank_owner_phone': row[6]
        }

    def _save_results(self):
        if not self.cases:
            print("Мошенники не найдены.")
            return

        print(f"Найдено совпадений: {len(self.cases)}. Сохранение...")

        df_main = pd.DataFrame(self.cases).drop(columns=['calls_data', 'market_data'])
        df_main.to_csv(f"{self.output_path}fraud_cases_detected.csv", index=False)

        neo_nodes, neo_edges = [], []

        for case in self.cases:
            f_acc = case['fraud_account']
            if case['has_market_activity']:
                pd.DataFrame(case['market_data']).to_csv(f"{self.output_path}fraud_market_{f_acc}.csv", index=False)
            if case['has_calls']:
                pd.DataFrame(case['calls_data']).to_csv(f"{self.output_path}fraud_calls_{f_acc}.csv", index=False)

            neo_nodes.append({
                'id': f"victim_{case['complaint_id']}", 'type': 'person', 'role': 'victim',
                'bank_id': case['complaint_id'], 'account': case['victim_account'], 'phone': case['victim_phone']
            })
            if case['fraud_bank_owner_id']:
                neo_nodes.append({
                    'id': f"fraud_{case['fraud_bank_owner_id']}", 'type': 'person', 'role': 'fraud',
                    'bank_id': case['fraud_bank_owner_id'], 'account': case['fraud_account'],
                    'phone': case['fraud_bank_owner_phone'], 'fio': case['fraud_bank_owner_fio']
                })
                neo_edges.append({
                    'from': f"victim_{case['complaint_id']}", 'to': f"fraud_{case['fraud_bank_owner_id']}",
                    'type': 'TRANSFERRED', 'amount': case['extracted_amount'], 'date': case['transaction_date']
                })

        pd.DataFrame(neo_nodes).to_csv(f"{self.output_path}neo4j_nodes.csv", index=False)
        pd.DataFrame(neo_edges).to_csv(f"{self.output_path}neo4j_edges.csv", index=False)
        print("Готово.")


if __name__ == "__main__":
    investigator = FraudInvestigator(
        db_path='data/ecosystem_data.db',
        complaints_path='data/bank_complaints.tsv',
        output_path='data/'
    )
    investigator.run()