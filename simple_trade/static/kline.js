/**
 * K线图页面脚本
 * 使用ECharts绘制专业K线图，支持买卖点标记
 * 
 * 优化：一次性加载数据，切换周期时前端筛选显示
 */

// ==================== 全局变量 ====================
let klineChart = null;
let allKlineData = [];    // 存储所有K线数据（一次性加载）
let allTradePoints = [];  // 存储所有交易点
let currentDays = 60;     // 当前显示天数
const MAX_LOAD_DAYS = 90; // 一次性加载的最大天数

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', function() {
    console.log('K线图页面初始化，股票代码:', stockCode);
    
    // 初始化ECharts
    initChart();
    
    // 绑定周期选择器事件
    bindPeriodSelector();
    
    // 一次性加载90天数据
    loadKlineData();
    
    // 窗口大小变化时重绘
    window.addEventListener('resize', function() {
        if (klineChart) {
            klineChart.resize();
        }
    });
});

// ==================== 初始化图表 ====================
function initChart() {
    const chartDom = document.getElementById('kline-chart');
    if (!chartDom) {
        console.error('找不到K线图容器');
        return;
    }
    
    // 清除加载状态
    const loadingEl = document.getElementById('chart-loading');
    if (loadingEl) {
        loadingEl.style.display = 'none';
    }
    
    klineChart = echarts.init(chartDom);
}

// ==================== 绑定周期选择器 ====================
function bindPeriodSelector() {
    const buttons = document.querySelectorAll('.period-btn');
    buttons.forEach(btn => {
        btn.addEventListener('click', function() {
            // 更新按钮状态
            buttons.forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            
            // 获取天数
            const days = parseInt(this.dataset.days) || 60;
            currentDays = days;
            
            // 前端筛选显示（不重新请求后端）
            renderKlineChartWithDays(days);
        });
    });
}

// ==================== 加载K线数据（一次性加载） ====================
async function loadKlineData() {
    showLoading();
    
    try {
        // 一次性加载90天数据
        const response = await fetch(`/api/kline/${encodeURIComponent(stockCode)}?days=${MAX_LOAD_DAYS}`);
        const result = await response.json();
        
        if (result.success && result.data) {
            // 更新股票信息
            updateStockInfo(result.data.stock_info);
            
            // 保存所有数据
            allKlineData = result.data.kline_data || [];
            allTradePoints = result.data.trade_points || [];
            
            console.log(`K线数据加载完成: ${allKlineData.length}条`);
            
            // 渲染默认周期（60天）
            renderKlineChartWithDays(currentDays);
            
            // 渲染交易记录（显示所有）
            renderTradeRecords(allTradePoints);
            
        } else {
            showError(result.message || '获取K线数据失败');
        }
    } catch (error) {
        console.error('加载K线数据失败:', error);
        showError('网络错误，请稍后重试');
    }
}

// ==================== 更新股票信息 ====================
function updateStockInfo(stockInfo) {
    if (!stockInfo) return;
    
    // 股票名称
    const nameEl = document.getElementById('stock-name');
    if (nameEl) {
        nameEl.textContent = stockInfo.name || stockCode;
    }
    
    // 当前价格
    const priceEl = document.getElementById('current-price');
    if (priceEl && stockInfo.cur_price) {
        priceEl.textContent = stockInfo.cur_price.toFixed(2);
    }
    
    // 涨跌幅
    const changeEl = document.getElementById('price-change');
    const changeValueEl = document.getElementById('price-change-value');
    const changeRateEl = document.getElementById('change-rate-value');
    
    if (stockInfo.change_rate !== undefined && stockInfo.change_rate !== null) {
        const isUp = stockInfo.change_rate >= 0;
        const sign = isUp ? '+' : '';
        
        if (changeEl) {
            changeEl.classList.remove('up', 'down');
            changeEl.classList.add(isUp ? 'up' : 'down');
        }
        
        if (changeValueEl && stockInfo.price_change !== undefined) {
            changeValueEl.textContent = `${sign}${stockInfo.price_change.toFixed(2)}`;
        }
        
        if (changeRateEl) {
            changeRateEl.textContent = `(${sign}${stockInfo.change_rate.toFixed(2)}%)`;
        }
    }
}

// ==================== 根据天数筛选并渲染K线图 ====================
function renderKlineChartWithDays(days) {
    // 检查数据
    if (!allKlineData || allKlineData.length === 0) {
        showError('暂无K线数据');
        return;
    }
    
    // 筛选数据：取最近N天，如果数据不足则显示全部
    const displayCount = Math.min(days, allKlineData.length);
    const klineData = allKlineData.slice(-displayCount);
    
    // 筛选对应日期范围内的交易点
    const startDate = klineData.length > 0 ? klineData[0][0] : null;
    const tradePoints = startDate 
        ? allTradePoints.filter(p => p.date >= startDate)
        : [];
    
    console.log(`显示K线: 请求${days}天, 实际显示${displayCount}天`);
    
    // 渲染K线图
    renderKlineChart(klineData, tradePoints);
}

// ==================== 渲染K线图 ====================
function renderKlineChart(klineData, tradePoints) {
    // 先检查数据
    if (!klineData || klineData.length === 0) {
        showError('暂无K线数据');
        return;
    }
    
    // 重新初始化图表（如果图表实例被销毁了）
    if (!klineChart) {
        const chartDom = document.getElementById('kline-chart');
        if (!chartDom) {
            showError('图表容器不存在');
            return;
        }
        // 清空加载状态的HTML，为ECharts初始化做准备
        chartDom.innerHTML = '';
        klineChart = echarts.init(chartDom);
    }
    
    // 处理数据格式
    // klineData格式: [[日期, 开盘, 收盘, 最低, 最高, 成交量], ...]
    const dates = klineData.map(item => item[0]);
    const ohlcData = klineData.map(item => [item[1], item[2], item[3], item[4]]);
    const volumeData = klineData.map((item, index) => {
        const isUp = item[2] >= item[1]; // 收盘 >= 开盘
        return {
            value: item[5],
            itemStyle: {
                color: isUp ? '#e74c3c' : '#27ae60'
            }
        };
    });

    // 调试日志：检查数据格式
    if (klineData.length > 0) {
        console.log('=== K线数据格式调试 ===');
        console.log('原始数据第一条:', klineData[0]);
        console.log('提取的OHLC第一条:', ohlcData[0]);
        console.log('格式说明: [开盘, 收盘, 最低, 最高]');
    }
    
    // 生成买卖点标记
    const markPoints = generateMarkPoints(dates, tradePoints);
    
    const option = {
        animation: false,
        backgroundColor: '#fff',
        tooltip: {
            trigger: 'axis',
            axisPointer: {
                type: 'cross'
            },
            borderWidth: 1,
            borderColor: '#ccc',
            padding: 10,
            textStyle: {
                color: '#333'
            },
            formatter: function(params) {
                const klineParam = params.find(p => p.seriesType === 'candlestick');
                const volumeParam = params.find(p => p.seriesName === '成交量');

                if (!klineParam) return '';

                const date = klineParam.name;
                const dataIndex = klineParam.dataIndex;

                // 直接从原始数据获取，不依赖 klineParam.value
                const rawData = klineData[dataIndex];
                if (!rawData) return '数据错误';

                const open = rawData[1];   // 开盘
                const close = rawData[2];  // 收盘
                const low = rawData[3];    // 最低
                const high = rawData[4];   // 最高

                let html = `<div style="font-weight:bold;margin-bottom:5px">${date}</div>`;
                html += `<div>开盘: <span style="color:#333;font-weight:bold">${open.toFixed(2)}</span></div>`;
                html += `<div>收盘: <span style="color:${close >= open ? '#e74c3c' : '#27ae60'};font-weight:bold">${close.toFixed(2)}</span></div>`;
                html += `<div>最低: <span style="color:#27ae60">${low.toFixed(2)}</span></div>`;
                html += `<div>最高: <span style="color:#e74c3c">${high.toFixed(2)}</span></div>`;

                if (volumeParam) {
                    const vol = volumeParam.value;
                    const volStr = vol >= 10000 ? (vol / 10000).toFixed(2) + '万' : vol;
                    html += `<div>成交量: <span style="font-weight:bold">${volStr}</span></div>`;
                }

                return html;
            }
        },
        legend: {
            show: false
        },
        grid: [
            {
                left: '60px',
                right: '40px',
                top: '30px',
                height: '60%'
            },
            {
                left: '60px',
                right: '40px',
                top: '75%',
                height: '15%'
            }
        ],
        xAxis: [
            {
                type: 'category',
                data: dates,
                scale: true,
                boundaryGap: true,
                axisLine: { lineStyle: { color: '#999' } },
                axisTick: { show: false },
                axisLabel: { 
                    color: '#666',
                    formatter: function(value) {
                        return value.substring(5); // 只显示MM-DD
                    }
                },
                splitLine: { show: false },
                min: 'dataMin',
                max: 'dataMax'
            },
            {
                type: 'category',
                gridIndex: 1,
                data: dates,
                scale: true,
                boundaryGap: true,
                axisLine: { lineStyle: { color: '#999' } },
                axisTick: { show: false },
                axisLabel: { show: false },
                splitLine: { show: false },
                min: 'dataMin',
                max: 'dataMax'
            }
        ],
        yAxis: [
            {
                scale: true,
                axisLine: { lineStyle: { color: '#999' } },
                axisTick: { show: false },
                axisLabel: { 
                    color: '#666',
                    formatter: '{value}'
                },
                splitLine: { 
                    show: true,
                    lineStyle: { color: '#f0f0f0' }
                }
            },
            {
                scale: true,
                gridIndex: 1,
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { show: false },
                splitLine: { show: false }
            }
        ],
        dataZoom: [
            {
                type: 'inside',
                xAxisIndex: [0, 1],
                start: 0,
                end: 100
            },
            {
                show: true,
                xAxisIndex: [0, 1],
                type: 'slider',
                bottom: 10,
                start: 0,
                end: 100,
                height: 20,
                borderColor: '#ddd',
                fillerColor: 'rgba(102, 126, 234, 0.2)',
                handleStyle: {
                    color: '#667eea'
                }
            }
        ],
        series: [
            {
                name: 'K线',
                type: 'candlestick',
                data: ohlcData,
                itemStyle: {
                    color: '#e74c3c',      // 阳线填充色（上涨）
                    color0: '#27ae60',     // 阴线填充色（下跌）
                    borderColor: '#e74c3c', // 阳线边框色
                    borderColor0: '#27ae60' // 阴线边框色
                },
                markPoint: markPoints
            },
            {
                name: '成交量',
                type: 'bar',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: volumeData,
                barWidth: '60%'
            }
        ]
    };
    
    klineChart.setOption(option, true);
}

// ==================== 生成买卖点标记 ====================
function generateMarkPoints(dates, tradePoints) {
    if (!tradePoints || tradePoints.length === 0) {
        return { data: [] };
    }
    
    const markData = [];
    
    tradePoints.forEach(point => {
        const dateIndex = dates.findIndex(d => d === point.date || d.startsWith(point.date));
        if (dateIndex === -1) return;
        
        const isBuy = point.type === 'buy';
        
        markData.push({
            name: isBuy ? 'B' : 'S',
            coord: [dateIndex, point.price],
            value: isBuy ? 'B' : 'S',
            symbol: 'pin',
            symbolSize: 40,
            symbolRotate: isBuy ? 0 : 180,
            itemStyle: {
                color: isBuy ? '#27ae60' : '#e74c3c'
            },
            label: {
                show: true,
                color: '#fff',
                fontWeight: 'bold',
                fontSize: 12,
                formatter: isBuy ? 'B' : 'S'
            }
        });
    });
    
    return {
        data: markData,
        animation: true
    };
}

// ==================== 渲染交易记录 ====================
function renderTradeRecords(records) {
    const listEl = document.getElementById('trade-records-list');
    const emptyEl = document.getElementById('trade-records-empty');
    
    if (!listEl) return;
    
    if (!records || records.length === 0) {
        if (emptyEl) emptyEl.style.display = 'block';
        return;
    }
    
    if (emptyEl) emptyEl.style.display = 'none';
    
    // 按日期倒序排列
    const sortedRecords = [...records].sort((a, b) => {
        return new Date(b.date) - new Date(a.date);
    });
    
    let html = '';
    sortedRecords.forEach(record => {
        const isBuy = record.type === 'buy';
        const typeClass = isBuy ? 'buy' : 'sell';
        const typeText = isBuy ? '买入' : '卖出';
        const icon = isBuy ? 'B' : 'S';
        
        html += `
            <div class="trade-record-item ${typeClass}">
                <div class="trade-record-icon">${icon}</div>
                <div class="trade-record-info">
                    <div>
                        <div class="trade-record-date">${record.date}</div>
                        <div class="trade-record-type">${typeText}</div>
                    </div>
                    <div class="trade-record-price">${record.price.toFixed(2)}</div>
                </div>
            </div>
        `;
    });
    
    listEl.innerHTML = html;
}

// ==================== 显示加载状态 ====================
function showLoading() {
    const chartDom = document.getElementById('kline-chart');
    if (chartDom) {
        chartDom.innerHTML = `
            <div class="loading-state">
                <div class="loading-spinner"></div>
                <span>正在加载K线数据...</span>
            </div>
        `;
    }
    
    // 如果图表已初始化，需要销毁
    if (klineChart) {
        klineChart.dispose();
        klineChart = null;
    }
}

// ==================== 显示错误状态 ====================
function showError(message) {
    const chartDom = document.getElementById('kline-chart');
    if (chartDom) {
        chartDom.innerHTML = `
            <div class="error-state">
                <div style="font-size: 3rem; opacity: 0.7;">⚠️</div>
                <p>${message}</p>
                <button class="back-btn" onclick="loadKlineData()" style="margin-top: 1rem;">
                    重新加载
                </button>
            </div>
        `;
    }
    
    if (klineChart) {
        klineChart.dispose();
        klineChart = null;
    }
}

// ==================== 工具函数：打开K线图页面 ====================
// 供其他页面调用
window.openKlinePage = function(code) {
    if (code) {
        window.location.href = `/kline?stock=${encodeURIComponent(code)}`;
    }
};
