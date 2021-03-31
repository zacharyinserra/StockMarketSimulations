import datetime as dt
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from time import sleep, time

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import requests
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

'''
Exponential Moving Average

EMA(t) = (V(t) * (s / (1 + d))) + EMA(y) * (1 - (s / (1 + d)))

EMA(t) = EMA today
V(t) = Value today
EMA(y) = EMA yesterday
s = Smoothing
d = Number of days

First EMA is SMA


Buy signals:
    When 50-day crosses above the 200-day
    When price crosses above a moving average
Sell signals:
    When 50-day drops below the 200-day
    When price drops below a moving average


Check EMA slopes to see if they cross
Execute simulated buy and sells based on signals
'''

# Get price trajectory based on second to last EMA minus the last EMA
#   If trajectory is positive, then the EMA is moving DOWN
#   If trajectory is negative, then the EMA is moving UP

# How to check if the lines cross tho?????
#   I'll just ask them nicely :)
#   OR maybe...
#   Second to last day values: X2 and Y2
#   Last day values: X1 and Y1
#   Scratch that...
#   If the lines are plotted can't I just find the slope of the lines and find points where they cross?? That's math isn't it??
#   Also, the derivative should show me slope AKA trajectory
#   I'm a math minor
#   I figured it out mostly


# Global variables
load_dotenv()
logfile = ""


class AlpacaServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)


def calculate_sma_first_day(days, sym_data, start_ind):
    sum = 0
    for i in range(days):
        d = sym_data[start_ind + 1 - i]
        sum += d['c']
    avg = sum / days
    return avg


def calculate_ema(start_sma, days, sym_data, start_ind):
    dic = {}
    smoothing_constant = 2
    weight = smoothing_constant / (days + 1)
    prev_ema = start_sma

    # Start at index of a year ago today
    # Get EMA for each day in list
    for i in range(start_ind + 1, len(sym_data)):
        d = sym_data[i]
        val_today = d['c']
        ema = (val_today - prev_ema) * weight + prev_ema
        dic[d['t']] = ema
        prev_ema = ema

    return dic


def line_intersection(line1, line2):
    xdiff = (line1[0][0] - line1[1][0], line2[0][0] - line2[1][0])
    ydiff = (line1[0][1] - line1[1][1], line2[0][1] - line2[1][1])

    def det(a, b):
        return a[0] * b[1] - a[1] * b[0]

    div = det(xdiff, ydiff)
    # if div == 0:
    #     # Lines parallel
    #     do_nothing()

    d = (det(*line1), det(*line2))
    x = det(d, xdiff) / div
    y = det(d, ydiff) / div
    return x, y


def sim_sell(symbol, symbol_data):
    log_info(logfile, "Attempting to sell shares for " + symbol)
    # Remove symbol and shares from "owned" shares
    with open("positions.json") as f:
        current_data = json.load(f)

    # Check if we own the symbol, if not return
    old_total = 0
    if not any(d["symbol"] == symbol for d in current_data):
        log_info(logfile, "We don't own dis: " + symbol)
        return 0
    else:
        index = next((index for (index, d) in enumerate(
            current_data) if d["symbol"] == symbol), None)
        old_total = current_data[index]["total"]
        del current_data[index]

    with open("positions.json", "w") as positions:
        json.dump(current_data, positions)

    # Use symbol_data to get the current price at which we a re selling the shares
    num_of_shares = 5
    price = symbol_data[-1]['c']
    new_total = price * num_of_shares
    net = new_total - old_total

    # Add total price of sold shares to account balance
    with open("bank.json") as bank:
        bank_data = json.load(bank)
        acc_balance = bank_data[0]["bank"] + new_total

    # Write bank data back to json file
    with open("bank.json", "w") as bank:
        json.dump([{"bank": acc_balance}], bank)

    # Add net to total profit
    with open("profit.json") as profit:
        total_profit = json.load(profit)
    new_profit = total_profit[0]["profit"] + net

    with open("profit.json", "w") as profit:
        json.dump([{"profit": new_profit}], profit)

    log_info(logfile, "Selling " + str(num_of_shares) + " shares for " +
             symbol + " at price $" + str(price))
    log_info(logfile, "Net: " + str(net))
    log_info(logfile, "New balance: " + str(acc_balance))
    return 1


def sim_buy(symbol, symbol_data):
    # Check if we own shares for this company or not? Maybe
    # Buy x number of shares up to a certain max price
    # Add symbol, shares, total price to "owned" shares
    log_info(logfile, "Attempting to buy shares for " + symbol)
    num_of_shares = 5
    price = symbol_data[-1]['c']
    total = price * num_of_shares

    with open("positions.json") as f:
        current_data = json.load(f)

    # Check if we already own shares for the symbol
    if any(d["symbol"] == symbol for d in current_data):
        log_info(logfile, "We own dis: " + symbol)
        return 0

    # Check if we have enough money then,
    # Subtract total price from bank amount
    with open("bank.json") as f:
        bank_data = json.load(f)
        acc_balance = bank_data[0]["bank"] - total
        if acc_balance <= 0:
            log_info(logfile, "Not enough money to buy " + symbol)
            return 0

    # Write bank data back to json file
    with open("bank.json", "w") as bank:
        json.dump([{"bank": acc_balance}], bank)

    new_data = {
        "symbol": symbol,
        "shares": num_of_shares,
        "price": price,
        "total": total
    }

    # Add new shares to exisiting shares and write to json file
    current_data.append(new_data)

    with open("positions.json", "w") as positions:
        json.dump(current_data, positions)

    log_info(logfile, "Buying " + str(num_of_shares) + " shares for " +
             symbol + " at price $" + str(price))
    log_info(logfile, "Total price: " + str(total))
    log_info(logfile, "New balance: " + str(acc_balance))
    return 1


def checktime():
    now = dt.time(hour=dt.datetime.now().hour, minute=dt.datetime.now(
    ).minute, second=dt.datetime.now().second)
    nine30 = dt.time(hour=9, minute=30, second=0)
    four30 = dt.time(hour=16, minute=30, second=0)
    if now > nine30 and now < four30:
        return True
    else:
        return False


def configure_logging():
    datenow = str(dt.datetime.now().strftime("%Y%m%d"))
    timenow = str(dt.datetime.now().strftime("%H%M%S"))
    folderpath = 'logs\\' + str(datenow)
    if not os.path.exists(folderpath):
        os.makedirs(folderpath)
    return folderpath + '\\transactions - ' + str(timenow) + '.log'


def log_info(logfile, string):
    now = str(dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    with open(logfile, 'a') as log:
        log.write(now + " ----- " + string + "\n")


def log_error(err):
    datenow = str(dt.datetime.now().strftime("%Y%m%d"))
    timenow = str(dt.datetime.now().strftime("%H:%M:%S"))
    folderpath = 'errors\\' + str(datenow)
    if not os.path.exists(folderpath):
        os.makedirs(folderpath)
    log_name = folderpath + '\\error.log'
    with open(log_name, 'a') as errorlog:
        datenow = str(dt.datetime.now().strftime("%Y-%m-%d"))
        errorlog.write(datenow + " " + timenow + " ----- " + err + "\n")


def cleanup():
    logs_path = r"C:\Code\StockMarketSimulations\logs"
    for folder in os.listdir(logs_path):
        folder_path = os.path.join(logs_path, folder)
        create_epoch = os.path.getctime(folder_path)
        time_delta = dt.datetime.now().timestamp() - create_epoch
        days_since = time_delta // (24 * 3600)
        if days_since > 7:
            shutil.rmtree(folder_path)

    errors_path = r"C:\Code\StockMarketSimulations\errors"
    for folder in os.listdir(errors_path):
        folder_path = os.path.join(errors_path, folder)
        create_epoch = os.path.getctime(folder_path)
        time_delta = dt.datetime.now().timestamp() - create_epoch
        days_since = time_delta // (24 * 3600)
        if days_since > 7:
            shutil.rmtree(folder_path)


symbols = []

f = open('nyse-listed_json.json')
data = json.load(f)

for i in data:
    symbols.append(i['ACT Symbol'])

f = open('nasdaq-listed-symbols_json.json')
data = json.load(f)

for i in data:
    if not i['Symbol'] in symbols:
        symbols.append(i['Symbol'])

f = open('s&p_json.json')
data = json.load(f)

for i in data:
    if not i['Symbol'] in symbols:
        symbols.append(i['Symbol'])

symbols.sort()

while True:
    cleanup()
    if checktime():
        logfile = configure_logging()

        print("Time to start")
        start = time()

        # Get todays date and the date a year ago today
        today = dt.date.today()
        year_ago = (today - relativedelta(years=1))

        num_requests = 0
        begin_requests = time()

        for symbol in symbols:
            buys = 0
            sells = 0
            try:
                # Keep track of requests per minute
                # Limit is 200
                # If 1 minute has not passed since begin_requests AND requests is 199, wait for a minute to have passed since begin_requests
                time_check = time() - begin_requests
                if num_requests >= 199 and time_check < 60:
                    time_to_wait = 60 - (time() - begin_requests)
                    # print("Waiting for request limit")
                    print("Number of request = " + str(num_requests) +
                          " - Waiting " + str(time_to_wait) + " seconds")
                    sleep(time_to_wait + 10)
                    num_requests = 0
                    begin_requests = time()
                elif num_requests >= 199 and time_check > 60:
                    num_requests = 0
                    begin_requests = time()

                # Get 500 days of data to perform calculations
                # 200 day EMA will require at least 450 days of data
                url = "https://data.alpaca.markets/v1/bars/day?symbols=" + symbol + \
                    "&limit=" + str(500) + "&until=" + \
                    str(today)  # + "T23:59:59Z"
                payload = {}
                headers = {
                    'APCA-API-KEY-ID': os.environ.get('APCA-API-KEY-ID'),
                    'APCA-API-SECRET-KEY': os.environ.get('APCA-API-SECRET-KEY')
                }

                response = requests.request(
                    "GET", url, headers=headers, data=payload)
                num_requests += 1

                if response.status_code == 429:
                    log_error("Too many requests: " + str(num_requests) + " " + symbol)
                    sleep(30)
                elif response.status_code != 200:
                    raise AlpacaServiceError(response.reason)

                data = json.loads(response.text)

                symbol_data = data[symbol]
                if len(symbol_data) > 0:
                    s = symbol_data[-1]
                else:
                    continue

                # DEBUG
                # sim_buy(symbol, symbol_data)
                # sim_sell(symbol, symbol_data)

                # Build list of epochs from symbol data to get finalized range of dates for calculations
                epochs = []
                for i in range(len(symbol_data)):
                    epochs.append(symbol_data[i]['t'])

                # Find year ago epoch to start calculations with
                year_ago = dt.datetime.combine(
                    year_ago, dt.datetime.min.time())
                year_ago_epoch = year_ago.timestamp()
                retry = 0
                while year_ago_epoch not in epochs and retry < 5:
                    ya_dt = dt.datetime.fromtimestamp(year_ago_epoch)
                    year_ago_epoch = (ya_dt + dt.timedelta(days=1)).timestamp()
                    retry += 1
                index = epochs.index(year_ago_epoch)

                # Get starting SMA to begin EMA calculations
                starting_sma200 = calculate_sma_first_day(
                    200, symbol_data, index)

                ema200_dic = calculate_ema(
                    starting_sma200, 200, symbol_data, index + 1)

                starting_sma50 = calculate_sma_first_day(
                    50, symbol_data, index)

                ema50_dic = calculate_ema(
                    starting_sma50, 50, symbol_data, index + 1)

                # Begin calculating line data to check for intersections
                second_to_last = epochs[-2]
                last = epochs[-1]

                # Calculate slope of line between the two last points
                slope200 = ema200_dic[last] - ema200_dic[second_to_last]
                slope50 = ema50_dic[last] - ema50_dic[second_to_last]

                # Last two points of each EMA
                point_A_200 = [1, ema200_dic[second_to_last]]
                point_B_200 = [2, ema200_dic[last]]

                point_A_50 = [1, ema50_dic[second_to_last]]
                point_B_50 = [2, ema50_dic[last]]

                intersection = line_intersection(
                    (point_A_200, point_B_200), (point_A_50, point_B_50))
                y_intersect = intersection[0]
                do_stuff = False

                now = str(dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                if y_intersect > 1 and y_intersect < 2:
                    do_stuff = True
                    print(symbol + " ----- " + now +
                          " ----- " + str(intersection))

                # If the x value of the intersection is between 1 and 2 then the lines cross
                # Compare slopes to see which line is crossing which, above or below
                # The line with the steeper slope is the one crossing the other?

                if slope200 > 0 and slope50 > 0:
                    print(symbol + " ----- " + now +
                          " ----- Both EMAs moving UP")
                    if do_stuff:
                        if slope200 > slope50:
                            # 200 day EMA has passed above the 50 day EMA
                            log_info(logfile, "Doing nothing for " + symbol)
                        if slope200 < slope50:
                            # 50 day EMA has passed above the 200 day EMA
                            # BUY
                            buys += sim_buy(symbol, symbol_data)

                elif slope200 > 0 and slope50 < 0:
                    print(symbol + " ----- " + now +
                          " ----- EMA 200 moving UP, EMA 50 moving DOWN")
                    if do_stuff:
                        # 200 day EMA has passed above the 50 day EMA
                        sells += sim_sell(symbol, symbol_data)

                elif slope200 < 0 and slope50 > 0:
                    print(symbol + " ----- " + now +
                          " ----- EMA 200 moving DOWN, EMA 50 moving UP")
                    if do_stuff:
                        # 50 day EMA has passed above the 200 day EMA
                        # BUY
                        buys += sim_buy(symbol, symbol_data)

                elif slope200 < 0 and slope50 < 0:
                    print(symbol + " ----- " + now +
                          " ----- Both EMAs moving DOWN")
                    if do_stuff:
                        if slope200 > slope50:
                            # 50 day EMA has passed below the 200 day EMA
                            # SELL
                            sells += sim_sell(symbol, symbol_data)
                        elif slope200 < slope50:
                            # 200 day EMA has passed below the 50 day EMA
                            log_info(logfile, "Doing nothing for " + symbol)

                else:
                    print(symbol + " ----- " + now + " ----- Somethings fucky")

            except IndexError:
                print("Index error for symbol", symbol)
            except ValueError:
                # Possible causes:
                # A gap in stock data, Ex. DCT has no data between Aug 2018 to Aug 2020, not sure why
                # Company has not been public for a full year + 200 market days
                print("Value error for symbol", symbol)
            except KeyError:
                print("Key error for symbol", symbol)
            except:
                e = sys.exc_info()[0]
                log_error(symbol + " " + str(e))

        print()
        print("--- %s seconds ---" % (time() - start))
        print("# of sells:", sells)
        print("# of buys:", buys)
    else:
        print("Not time, waiting for market to open")
        sleep(600)
        # Wait until 9:30 AM instead of snoozing
