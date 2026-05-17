path = r'd:\Program Files\futu_trade_sys\futu-trade-frontend\src\lib\api\enhanced-heat.ts'
with open(path, 'rb') as f:
    data = f.read()
# Fix literal \\r followed by \r\n -> just \r\n
fixed = data.replace(b'\\r\r\n', b'\r\n')
count = data.count(b'\\r\r\n')
with open(path, 'wb') as f:
    f.write(fixed)
print(f'Fixed {count} occurrences of literal backslash-r')
