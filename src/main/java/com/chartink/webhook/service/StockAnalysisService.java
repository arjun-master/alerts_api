package com.chartink.webhook.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Map;

@Slf4j
@Service
public class StockAnalysisService {
    private final FyersService fyersService;

    public StockAnalysisService(FyersService fyersService) {
        this.fyersService = fyersService;
    }

    public record StockReturn(double oneDayReturn, double threeDayReturn, double oneWeekReturn) {}

    public Mono<Map<String, StockReturn>> getStockReturnsMap(String[] stocks) {
        return Flux.fromArray(stocks)
                .flatMap(stock -> getStockReturns(stock.trim())
                        .map(returns -> Map.entry(stock.trim(), returns)))
                .collectMap(Map.Entry::getKey, Map.Entry::getValue);
    }

    public Mono<StockReturn> getStockReturns(String symbol) {
        return fyersService.getHistoricalData(symbol, 7)
                .map(data -> new StockReturn(
                    data.oneDayReturn(),
                    data.threeDayReturn(),
                    data.oneWeekReturn()
                ));
    }

    public record StockHistoricalData(double prevDayClose, double threeDaysBackClose, double sevenDaysBackClose) {}

    public Mono<Map<String, StockHistoricalData>> getStockHistoricalData(String[] symbols) {
        return Flux.fromArray(symbols)
                .flatMap(symbol -> {
                    LocalDate today = LocalDate.now();
                    LocalDate prevDay = today.minusDays(1);
                    LocalDate threeDaysBack = today.minusDays(3);
                    LocalDate sevenDaysBack = today.minusDays(7);
                    DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd");
                    String symbolWithExchange = "NSE:" + symbol + "-EQ";
                    return Mono.just(symbolWithExchange)
                            .flatMap(sym -> {
                                try {
                                    JSONObject prevDayData = fyersHistoricalDataService.getHistoricalData(sym, "D", prevDay, prevDay);
                                    JSONObject threeDaysData = fyersHistoricalDataService.getHistoricalData(sym, "D", threeDaysBack, threeDaysBack);
                                    JSONObject sevenDaysData = fyersHistoricalDataService.getHistoricalData(sym, "D", sevenDaysBack, sevenDaysBack);
                                    double prevDayClose = prevDayData.getJSONArray("candles").getJSONArray(0).getDouble(4);
                                    double threeDaysBackClose = threeDaysData.getJSONArray("candles").getJSONArray(0).getDouble(4);
                                    double sevenDaysBackClose = sevenDaysData.getJSONArray("candles").getJSONArray(0).getDouble(4);
                                    return Mono.just(new StockHistoricalData(prevDayClose, threeDaysBackClose, sevenDaysBackClose));
                                } catch (Exception e) {
                                    log.error("Error fetching historical data for {}: {}", sym, e.getMessage());
                                    return Mono.just(new StockHistoricalData(0.0, 0.0, 0.0));
                                }
                            })
                            .map(data -> Map.entry(symbol, data));
                })
                .collectMap(Map.Entry::getKey, Map.Entry::getValue);
    }
} 