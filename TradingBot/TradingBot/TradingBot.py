import time
from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.enums import *
import os
import decimal

# Enter your API key and secret here
api_key = "<Binance API Key>"
secret_key = "<Binance Secret Key>"

# Set up the client object
client = Client(api_key=api_key, api_secret=secret_key, testnet=True)

# Set the symbol to trade
symbol = "BTCBUSD"
symbol_p = "BUSD" #Primary symbol
symbol_s = "BTC" #Secondary symbol

# Set the stop loss percentage
stop_loss = decimal.Decimal(0.01) # 2% of buying price

min_invest = 20

# Set the interval for checking the market
interval_1m = KLINE_INTERVAL_1MINUTE
interval_1h = KLINE_INTERVAL_1HOUR
interval_4h = KLINE_INTERVAL_4HOUR

# Set the time to wait between trades
trade_wait = 10  # 10 seconds
inter_trade_wait = 0.1 # 0.1 second

# Define a function to calculate the moving average
def get_moving_average_m(symbol, interval, period):
    klines = client.get_historical_klines(symbol, interval, f"{period} minutes ago UTC")
    closes = [decimal.Decimal(x[4]) for x in klines]
    ma = sum(closes) / len(closes)
    return ma

def get_moving_average_h(symbol, interval, period):
    klines = client.get_historical_klines(symbol, interval, f"{period} hours ago UTC")
    closes = [decimal.Decimal(x[4]) for x in klines]
    ma = sum(closes) / len(closes)
    return ma

# Define a function to calculate the minimum trade quantity for a symbol
def get_min_trade_qty(symbol):
    info = client.get_symbol_info(symbol)
    filters = info['filters']
    min_qty_filter = [f for f in filters if f['filterType'] == 'LOT_SIZE'][0]
    min_trade_qty = decimal.Decimal(min_qty_filter['minQty'])
    return min_trade_qty

def get_opportunity():
    # Calculate the 20-period and 50-period moving averages
    ma20_1m = get_moving_average_m(symbol, interval_1m, 20)
    ma50_1m = get_moving_average_m(symbol, interval_1m, 50)

    ma20_1h = get_moving_average_h(symbol, interval_1h, 20)
    ma50_1h = get_moving_average_h(symbol, interval_1h, 50)

    ma20_4h = get_moving_average_h(symbol, interval_4h, 20)
    ma50_4h = get_moving_average_h(symbol, interval_4h, 50)
    #os.system("cls")
    #print(f"{ma20_1m > ma50_1m and ma20_1h > ma50_1h and ma20_4h > ma50_4h} -> ma20_1m = {ma20_1m} ma50_1m = {ma50_1m} | ma20_1h = {ma20_1h} ma50_1h = {ma50_1h} | ma20_4h = {ma20_4h} ma50_4h = {ma50_4h}")
    
    # Check if the 20-period moving average crosses above the 50-period moving average
    return ma20_1m > ma50_1m and ma20_1h > ma50_1h and ma20_4h > ma50_4h

# Enter a loop to continuously check the market and execute trades
while True:
    if get_opportunity() or True:
        # Get the minimum trade quantity for the symbol
        min_trade_qty = get_min_trade_qty(symbol)

        # Get the balance for the base asset
        base_asset_balance = client.get_asset_balance(asset=symbol_p)['free']

        # Calculate the trade amount based on the balance and minimum trade quantity
        # Get the minimum notional value for the symbol
        symbol_info = client.get_symbol_info(symbol)
        #print(symbol_info)
        min_notional = decimal.Decimal(symbol_info['filters'][2]['minNotional'])
        #print(symbol_info['filters'])
        # Calculate the trade amount based on the balance and minimum trade quantity
        trade_amount = min(decimal.Decimal(base_asset_balance), min_invest) #// min_notional * min_notional
        #print(f"Base asset balance={base_asset_balance} TradeAmount={trade_amount}")
        if trade_amount < min_notional:
            print("You do not have enough coins for trading")
            continue
        #trade_amount = max(trade_amount, min_notional)
        # Place a market buy order
        try:
            buy_order = client.order_market_buy(
                symbol=symbol,
                quoteOrderQty=trade_amount
            )
        except BinanceAPIException as e:
            print('Error 0:', e)
            continue

        # Calculate the stop loss price
        entry_price = decimal.Decimal(buy_order['fills'][0]['price'])
        stop_loss_price = entry_price * (1 - stop_loss)

        # get the minimum and maximum price and quantity allowed for the symbol
        min_price = decimal.Decimal(symbol_info['filters'][0]['minPrice'])
        max_price = decimal.Decimal(symbol_info['filters'][0]['maxPrice'])
        price_step = decimal.Decimal(symbol_info['filters'][0]['tickSize'])
        min_qty = decimal.Decimal(symbol_info['filters'][1]['minQty'])
        max_qty = decimal.Decimal(symbol_info['filters'][1]['maxQty'])
        qty_step = decimal.Decimal(symbol_info['filters'][1]['stepSize'])

        price = entry_price * (1 + stop_loss)
        quantity = decimal.Decimal(buy_order['executedQty'])
        # round the price and quantity to the appropriate precision
        price = round(price / price_step) * price_step
        stop_loss_price = round(stop_loss_price / price_step) * price_step
        quantity = round(quantity / qty_step) * qty_step
        # ensure the price and quantity are within the allowed range
        price = min(max(price, min_price), max_price)
        stop_loss_price = min(max(stop_loss_price, min_price), max_price)
        quantity = min(max(quantity, min_qty), max_qty)

        # calculate the order value
        order_value = round(price * quantity, 8)
        # check if the order value meets the minimum notional requirement
        if order_value < min_notional:
            quantity = round(min_notional / price, 8)
            print(f"Adjusted quantity to meet minimum notional requirement: {quantity}")

        #print(f"PriceStep={price_step} QtyStep={qty_step} PriceMin={min_price} QtyMin={min_qty}")
        #print(f"Price={price} StopLoss={stop_loss_price} Quantity={buy_order['executedQty']} StopTimeIn={TIME_IN_FORCE_GTC}")
        
        # Place an OCO order to sell if the price drops to the stop loss level
        oco_order = client.create_oco_order(
            symbol=symbol,
            quantity=quantity,
            side=SIDE_SELL,
            price=price,
            stopPrice=stop_loss_price,
            stopLimitPrice=stop_loss_price,
            stopLimitTimeInForce=TIME_IN_FORCE_GTC
        )

        # Wait for the order to be filled or the stop loss to be triggered
        while True:
            # Get the current price
            ticker = client.get_ticker(symbol=symbol)
            current_price = decimal.Decimal(ticker['lastPrice'])
            order_stop_price = decimal.Decimal(oco_order["orderReports"][0]['price'])
            order_profit_price = decimal.Decimal(oco_order["orderReports"][1]['price'])
            #print(oco_order)
            print(f"StopPrice={order_stop_price} ProfitPrice={order_profit_price}")
            # Check if the price has reached the stop loss level
            if current_price <= order_stop_price:
                print("Canceling the TAKE_PROFIT order")
                # Cancel the take profit order
                try:
                    client.cancel_order(
                        symbol=symbol,
                        orderId=oco_order['orderListId'],
                        listClientOrderId=oco_order['listClientOrderId']
                    )
                except BinanceAPIException as e:
                    print('Error 1:', e)

                # Place a market sell order
                try:
                    sell_order = client.order_market_sell(
                        symbol=symbol,
                        quantity=decimal.Decimal(buy_order['executedQty'])
                    )
                except BinanceAPIException as e:
                    print('Error 2:', e)
                    continue

                # Exit the loop
                break
            
            
            # Check if the price has reached the take profit level
            if current_price >= order_profit_price:
                print("Canceling the STOP_LOSS order")
                # Cancel the stop loss order
                try:
                    client.cancel_order(
                        symbol=symbol,
                        orderId=oco_order['orderListId'],
                        listClientOrderId=oco_order['listClientOrderId']
                    )
                except BinanceAPIException as e:
                    print('Error 3:', e)

                # Place a market sell order
                try:
                    sell_order = client.order_market_sell(
                        symbol=symbol,
                        quantity=decimal.Decimal(buy_order['executedQty'])
                    )
                except BinanceAPIException as e:
                    print('Error 4:', e)
                    continue

                # Exit the loop
                break

            # Wait for the next iteration
            time.sleep(inter_trade_wait)

    # Wait for the next iteration
    time.sleep(trade_wait)