package com.chartink.webhook.controller;

import com.chartink.webhook.service.FyersService;
import com.chartink.webhook.service.StockAnalysisService;
import com.chartink.webhook.service.TelegramService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;

@Slf4j
@RestController
@RequestMapping("/api/test")
@RequiredArgsConstructor
public class TestController {
    private final FyersService fyersService;
    private final StockAnalysisService stockAnalysisService;
    private final TelegramService telegramService;

    @Autowired
    public TestController(FyersService fyersService, StockAnalysisService stockAnalysisService, TelegramService telegramService) {
        this.fyersService = fyersService;
        this.stockAnalysisService = stockAnalysisService;
        this.telegramService = telegramService;
    }

    @GetMapping("/stock/{symbol}")
    public Mono<FyersService.StockData> testStockData(@PathVariable String symbol) {
        log.info("Testing stock data for symbol: {}", symbol);
        return fyersService.getStockData(symbol);
    }

    @GetMapping("/history/{symbol}")
    public Mono<FyersService.HistoricalData> testHistoricalData(@PathVariable String symbol) {
        log.info("Testing historical data for symbol: {}", symbol);
        return fyersService.getHistoricalData(symbol, 7);
    }

    @PostMapping("/send-historical-test")
    public Mono<String> sendHistoricalTestMessage() {
        String[] symbols = {"RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "SBIN", "BAJFINANCE", "BHARTIARTL", "KOTAKBANK"};
        return stockAnalysisService.getStockHistoricalData(symbols)
            .flatMap(dataMap -> {
                StringBuilder msg = new StringBuilder();
                msg.append("<b>Stock Historical Close Prices</b>\n\n");
                dataMap.forEach((symbol, data) -> {
                    msg.append("<b>").append(symbol).append("</b>\n");
                    msg.append("Prev Day Close: ").append(data.prevDayClose()).append("\n");
                    msg.append("3 Days Back Close: ").append(data.threeDaysBackClose()).append("\n");
                    msg.append("7 Days Back Close: ").append(data.sevenDaysBackClose()).append("\n\n");
                });
                return telegramService.sendCustomMessage(msg.toString());
            });
    }
} 