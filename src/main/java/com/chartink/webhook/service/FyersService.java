package com.chartink.webhook.service;

import com.chartink.webhook.config.FyersConfig;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tts.in.model.FyersClass;
import com.tts.in.model.StockHistoryModel;
import com.tts.in.utilities.Tuple;
import lombok.extern.slf4j.Slf4j;
import org.json.JSONObject;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.concurrent.ConcurrentHashMap;

@Slf4j
@Service
public class FyersService {
    private final FyersConfig fyersConfig;
    private final ObjectMapper objectMapper;
    private final ConcurrentHashMap<String, CachedStockData> stockCache;
    private final FyersClass fyersClass;

    public FyersService(FyersConfig fyersConfig, ObjectMapper objectMapper) {
        this.fyersConfig = fyersConfig;
        this.objectMapper = objectMapper;
        this.stockCache = new ConcurrentHashMap<>();
        this.fyersClass = FyersClass.getInstance();
        this.fyersClass.accessToken = fyersConfig.getAccessToken();
    }

    public record StockData(double ltp, double change, double changePercent) {}
    
    private record CachedStockData(StockData data, LocalDateTime timestamp) {
        boolean isExpired() {
            return LocalDateTime.now().isAfter(timestamp.plusMinutes(1));
        }
    }

    public Mono<StockData> getStockData(String symbol) {
        // Check cache first
        CachedStockData cachedData = stockCache.get(symbol);
        if (cachedData != null && !cachedData.isExpired()) {
            log.info("Using cached data for symbol: {}", symbol);
            return Mono.just(cachedData.data());
        }

        String fyersSymbol = "NSE:" + symbol + "-EQ";
        
        return Mono.fromCallable(() -> {
            Tuple<JSONObject, JSONObject> result = fyersClass.GetStockQuotes(fyersSymbol);
            JSONObject response = result.Item1();
            
            if (!"ok".equals(response.getString("s"))) {
                throw new RuntimeException("Error from Fyers: " + response.optString("message"));
            }

            JsonNode quote = objectMapper.readTree(response.toString())
                .path("d").get(0);

            double ltp = quote.path("ltp").asDouble();
            double prevClose = quote.path("prev_close_price").asDouble();
            double change = ltp - prevClose;
            double changePercent = (change / prevClose) * 100;

            StockData stockData = new StockData(ltp, change, changePercent);
            stockCache.put(symbol, new CachedStockData(stockData, LocalDateTime.now()));
            
            return stockData;
        }).subscribeOn(Schedulers.boundedElastic())
        .onErrorResume(error -> {
            log.error("Error fetching data from Fyers for {}: {}", symbol, error.getMessage());
            return cachedData != null ? 
                    Mono.just(cachedData.data()) : 
                    Mono.just(new StockData(0.0, 0.0, 0.0));
        });
    }

    public Mono<HistoricalData> getHistoricalData(String symbol, int days) {
        String fyersSymbol = "NSE:" + symbol + "-EQ";
        long toDate = LocalDateTime.now().toEpochSecond(ZoneOffset.UTC);
        long fromDate = LocalDateTime.now().minusDays(days).toEpochSecond(ZoneOffset.UTC);
        
        return Mono.fromCallable(() -> {
            StockHistoryModel historyModel = new StockHistoryModel();
            historyModel.Symbol = fyersSymbol;
            historyModel.Resolution = "D";
            historyModel.DateFormat = "1";
            historyModel.RangeFrom = String.valueOf(fromDate);
            historyModel.RangeTo = String.valueOf(toDate);
            historyModel.ContFlag = 1;

            Tuple<JSONObject, JSONObject> result = fyersClass.GetStockHistory(historyModel);
            JSONObject response = result.Item1();
            
            if (!"ok".equals(response.getString("s"))) {
                throw new RuntimeException("Error from Fyers: " + response.optString("message"));
            }

            JsonNode candles = objectMapper.readTree(response.toString())
                .path("candles");

            if (candles.size() < 2) {
                throw new RuntimeException("Insufficient historical data");
            }

            double currentClose = candles.get(candles.size() - 1).get(4).asDouble();
            double oneDayAgoClose = candles.get(candles.size() - 2).get(4).asDouble();
            double threeDayAgoClose = candles.size() > 4 ? 
                    candles.get(candles.size() - 4).get(4).asDouble() : oneDayAgoClose;
            double oneWeekAgoClose = candles.size() > 7 ? 
                    candles.get(candles.size() - 7).get(4).asDouble() : threeDayAgoClose;

            return new HistoricalData(
                calculateReturn(oneDayAgoClose, currentClose),
                calculateReturn(threeDayAgoClose, currentClose),
                calculateReturn(oneWeekAgoClose, currentClose)
            );
        }).subscribeOn(Schedulers.boundedElastic())
        .onErrorResume(error -> {
            log.error("Error fetching historical data from Fyers for {}: {}", symbol, error.getMessage());
            return Mono.just(new HistoricalData(0.0, 0.0, 0.0));
        });
    }

    private double calculateReturn(double initialPrice, double finalPrice) {
        return ((finalPrice - initialPrice) / initialPrice) * 100;
    }

    public record HistoricalData(double oneDayReturn, double threeDayReturn, double oneWeekReturn) {}
} 