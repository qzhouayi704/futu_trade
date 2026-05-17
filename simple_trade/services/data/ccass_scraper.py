"""
HKEX CCASS 持仓数据爬取器

从港交所中央结算系统 (CCASS) 获取每日经纪商持仓数据。
数据延迟 T+1，但可追踪机构的持仓变化趋势。

数据来源: https://www3.hkexnews.hk/sdw/search/searchsdw.aspx
"""

import logging
import re
import json
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# CCASS 新版 API (JSON)
CCASS_SEARCH_URL = "https://www3.hkexnews.hk/sdw/search/searchsdw.aspx"


class CCASSScraper:
    """HKEX CCASS 持仓数据爬取器"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': CCASS_SEARCH_URL,
        })
        self._viewstate = None
        self._viewstate_gen = None
        self._event_validation = None

    def _init_session(self) -> bool:
        """初始化会话，获取 ASP.NET 表单令牌"""
        try:
            r = self.session.get(CCASS_SEARCH_URL, timeout=15)
            r.raise_for_status()

            self._viewstate = self._extract_field(r.text, '__VIEWSTATE')
            self._viewstate_gen = self._extract_field(r.text, '__VIEWSTATEGENERATOR')

            if self._viewstate:
                logger.info("CCASS 会话初始化成功")
                return True
            else:
                logger.error("CCASS 会话初始化失败: 未找到 __VIEWSTATE")
                return False
        except Exception as e:
            logger.error(f"CCASS 会话初始化异常: {e}")
            return False

    @staticmethod
    def _extract_field(html: str, field_name: str) -> Optional[str]:
        """从 HTML 中提取 ASP.NET 隐藏字段值"""
        pattern = rf'id="{field_name}".*?value="([^"]*)"'
        match = re.search(pattern, html, re.DOTALL)
        return match.group(1) if match else None

    def fetch_shareholding(self, stock_code: str, date: Optional[str] = None) -> dict:
        """获取指定股票在指定日期的 CCASS 持仓数据

        Args:
            stock_code: 港股代码（纯数字，如 '02656' 或 '700'）
            date: 日期字符串 'YYYY/MM/DD'，默认为昨天

        Returns:
            {
                'stock_code': '02656',
                'date': '2026/05/07',
                'total_issued_shares': 1234567890,
                'participants': [
                    {
                        'participant_id': 'C00010',
                        'name': '中国银河国际证券',
                        'shareholding': 12345678,
                        'percent': 5.23,
                    },
                    ...
                ]
            }
        """
        # 标准化股票代码（去掉 HK. 前缀，补零到5位）
        code = stock_code.replace('HK.', '').lstrip('0') or '0'
        code_padded = code.zfill(5)

        if date is None:
            yesterday = datetime.now() - timedelta(days=1)
            # 跳过周末
            if yesterday.weekday() == 6:  # Sunday
                yesterday -= timedelta(days=2)
            elif yesterday.weekday() == 5:  # Saturday
                yesterday -= timedelta(days=1)
            date = yesterday.strftime('%Y/%m/%d')

        logger.info(f"获取 CCASS 数据: {code_padded}, 日期: {date}")

        if not self._init_session():
            return {'error': '会话初始化失败', 'participants': []}

        # POST 搜索请求
        try:
            form_data = {
                '__EVENTTARGET': '',
                '__EVENTARGUMENT': '',
                '__VIEWSTATE': self._viewstate,
                '__VIEWSTATEGENERATOR': self._viewstate_gen or '',
                'today': datetime.now().strftime('%Y%m%d'),
                'sortBy': 'shareholding',
                'sortDirection': 'desc',
                'alertMsg': '',
                'txtShareholdingDate': date,
                'txtStockCode': code_padded,
                'txtStockName': '',
                'txtParticipantID': '',
                'txtParticipantName': '',
                'btnSearch': 'Search',
            }

            r = self.session.post(CCASS_SEARCH_URL, data=form_data, timeout=30)
            r.raise_for_status()

            return self._parse_results(r.text, code_padded, date)

        except Exception as e:
            logger.error(f"CCASS 搜索请求失败: {e}")
            return {'error': str(e), 'participants': []}

    def _parse_results(self, html: str, stock_code: str, date: str) -> dict:
        """解析 CCASS 搜索结果 HTML

        HKEX 页面结构：每行 <tr> 包含多个 <td>，
        每个 <td> 内有 <div class="mobile-list-body"> 存放实际值。
        列顺序: Participant ID | Name | Address | Shareholding | %
        """
        result = {
            'stock_code': stock_code,
            'date': date,
            'participants': [],
        }

        # 找到 <tbody> 中的所有 <tr>
        tbody = re.search(r'<tbody>(.*?)</tbody>', html, re.DOTALL)
        if not tbody:
            logger.warning("未找到 tbody")
            return result

        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody.group(1), re.DOTALL)

        for tr in rows:
            # 提取每个 td 中 mobile-list-body 的内容
            bodies = re.findall(
                r'<div class="mobile-list-body">(.*?)</div>',
                tr, re.DOTALL
            )
            # 期望: [participant_id, name, address, shareholding, percent]
            if len(bodies) >= 4:
                pid = self._clean_html(bodies[0]).strip()
                name = self._clean_html(bodies[1]).strip()
                # bodies[2] 是 address，跳过
                holding_idx = 3
                holding_str = self._clean_html(bodies[holding_idx]).strip().replace(',', '')

                pct_str = '0'
                if len(bodies) >= 5:
                    pct_str = self._clean_html(bodies[4]).strip().replace('%', '')

                if pid and holding_str.isdigit():
                    try:
                        result['participants'].append({
                            'participant_id': pid,
                            'name': name,
                            'shareholding': int(holding_str),
                            'percent': float(pct_str) if pct_str else 0.0,
                        })
                    except (ValueError, TypeError):
                        pass

        # 按持仓量排序
        result['participants'].sort(key=lambda x: x['shareholding'], reverse=True)

        logger.info(f"CCASS 解析完成: {stock_code} @ {date}, "
                     f"找到 {len(result['participants'])} 个参与者")

        return result

    @staticmethod
    def _clean_html(text: str) -> str:
        """清理 HTML 标签"""
        return re.sub(r'<[^>]+>', '', text).strip()

    def fetch_multi_day(self, stock_code: str, days: int = 5) -> list:
        """获取多日数据用于对比持仓变化

        Args:
            stock_code: 港股代码
            days: 获取天数（默认5天）

        Returns:
            [{'date': ..., 'participants': [...]}, ...]
        """
        results = []
        current = datetime.now() - timedelta(days=1)

        for _ in range(days * 2):  # 多迭代以跳过周末
            if len(results) >= days:
                break
            if current.weekday() < 5:  # 跳过周末
                date_str = current.strftime('%Y/%m/%d')
                data = self.fetch_shareholding(stock_code, date_str)
                if data.get('participants'):
                    results.append(data)
            current -= timedelta(days=1)

        return results

    def get_holding_changes(self, stock_code: str, days: int = 3) -> dict:
        """计算持仓变化（核心功能）

        对比最近 N 天的数据，找出增持/减持最大的经纪商。

        Returns:
            {
                'stock_code': '02656',
                'latest_date': '2026/05/07',
                'compare_date': '2026/05/05',
                'top_increases': [{'name': ..., 'change': +12345}, ...],
                'top_decreases': [{'name': ..., 'change': -54321}, ...],
                '_raw_latest': [...],   # 原始持仓数据（用于 DB 存储）
                '_raw_compare': [...],  # 原始持仓数据（用于 DB 存储）
            }
        """
        multi = self.fetch_multi_day(stock_code, days=days)
        if len(multi) < 2:
            return {
                'stock_code': stock_code,
                'error': f'数据不足（仅获取 {len(multi)} 天）',
                'top_increases': [],
                'top_decreases': [],
            }

        latest = multi[0]
        prev = multi[-1]

        # 构建参与者持仓映射
        latest_map = {p['participant_id']: p for p in latest['participants']}
        prev_map = {p['participant_id']: p for p in prev['participants']}

        changes = []
        all_ids = set(latest_map.keys()) | set(prev_map.keys())
        for pid in all_ids:
            curr = latest_map.get(pid)
            old = prev_map.get(pid)

            curr_holding = curr['shareholding'] if curr else 0
            old_holding = old['shareholding'] if old else 0
            change = curr_holding - old_holding

            if change != 0:
                name = (curr or old)['name']
                changes.append({
                    'participant_id': pid,
                    'name': name,
                    'current_holding': curr_holding,
                    'prev_holding': old_holding,
                    'change': change,
                    'change_shares': change,
                })

        changes.sort(key=lambda x: x['change'], reverse=True)

        top_inc = [c for c in changes if c['change'] > 0][:10]
        top_dec = [c for c in changes if c['change'] < 0][-10:]
        top_dec.sort(key=lambda x: x['change'])

        # 转换原始参与者数据为 DB 存储格式
        raw_latest = [
            {'id': p['participant_id'], 'name': p['name'],
             'shareholding': p['shareholding'], 'percent': p.get('percent', 0)}
            for p in latest['participants']
        ]
        raw_compare = [
            {'id': p['participant_id'], 'name': p['name'],
             'shareholding': p['shareholding'], 'percent': p.get('percent', 0)}
            for p in prev['participants']
        ]

        return {
            'stock_code': stock_code,
            'latest_date': latest['date'],
            'compare_date': prev['date'],
            'top_increases': top_inc,
            'top_decreases': top_dec,
            '_raw_latest': raw_latest,
            '_raw_compare': raw_compare,
        }

    def _get_recent_trading_dates(self, days: int = 3) -> list:
        """获取最近 N 个交易日的日期字符串列表（跳过周末）

        Returns:
            ['2026/05/07', '2026/05/06', ...]
        """
        dates = []
        current = datetime.now() - timedelta(days=1)
        for _ in range(days * 2):
            if len(dates) >= days:
                break
            if current.weekday() < 5:
                dates.append(current.strftime('%Y/%m/%d'))
            current -= timedelta(days=1)
        return dates


# 测试入口
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    scraper = CCASSScraper()
    result = scraper.fetch_shareholding('02656')
    print(json.dumps(result, indent=2, ensure_ascii=False))

