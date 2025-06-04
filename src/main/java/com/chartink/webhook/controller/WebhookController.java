package com.chartink.webhook.controller;

import com.chartink.webhook.dto.WebhookResponse;
import com.chartink.webhook.model.WebhookData;
import com.chartink.webhook.service.StockAnalysisService;
import com.chartink.webhook.service.TelegramService;
import io.micrometer.core.annotation.Timed;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.stream.Collectors;

@Slf4j
@RestController
@RequestMapping("/webhook")
@RequiredArgsConstructor
public class WebhookController {

    private final TelegramService telegramService;
    private final StockAnalysisService stockAnalysisService;

    @PostMapping(produces = MediaType.APPLICATION_JSON_VALUE)
    @Timed(value = "webhook.process", description = "Time taken to process webhook")
    public Mono<ResponseEntity<WebhookResponse>> handleWebhook(@RequestBody WebhookData webhookData) {
        log.info("Received webhook for scan: {}", webhookData.getScanName());

        return processStockData(webhookData)
                .flatMap(stockAnalysis -> 
                    telegramService.sendMessage(webhookData)
                        .map(response -> ResponseEntity.ok(
                            WebhookResponse.builder()
                                .message("Webhook processed successfully")
                                .success(true)
                                .scanName(webhookData.getScanName())
                                .alertName(webhookData.getAlertName())
                                .stockAnalysis(stockAnalysis)
                                .triggeredAt(webhookData.getTriggeredAt())
                                .build()
                        ))
                        .onErrorResume(error -> {
                            log.error("Error processing webhook: {}", error.getMessage());
                            return Mono.just(ResponseEntity.status(500)
                                    .body(WebhookResponse.builder()
                                            .message("Error processing webhook: " + error.getMessage())
                                            .success(false)
                                            .scanName(webhookData.getScanName())
                                            .alertName(webhookData.getAlertName())
                                            .stockAnalysis(stockAnalysis)
                                            .triggeredAt(webhookData.getTriggeredAt())
                                            .build()));
                        }))
                .doOnSuccess(response -> log.info("Webhook processing completed for scan: {}", webhookData.getScanName()));
    }

    private Mono<Map<String, WebhookResponse.StockAnalysis>> processStockData(WebhookData webhookData) {
        String[] stocks = webhookData.getStocks().split(",\\s*");
        String[] prices = webhookData.getTriggerPrices().split(",\\s*");
        Map<String, String> priceMap = new HashMap<>();
        
        for (int i = 0; i < stocks.length && i < prices.length; i++) {
            priceMap.put(stocks[i].trim(), prices[i].trim());
        }

        return Flux.fromArray(stocks)
                .map(String::trim)
                .flatMap(stock -> stockAnalysisService.getStockReturns(stock)
                        .map(returns -> Map.entry(stock, 
                            WebhookResponse.StockAnalysis.builder()
                                .triggerPrice(priceMap.getOrDefault(stock, "N/A"))
                                .returns(WebhookResponse.Returns.builder()
                                    .oneDay(returns.oneDayReturn())
                                    .threeDay(returns.threeDayReturn())
                                    .oneWeek(returns.oneWeekReturn())
                                    .build())
                                .build())))
                .collectMap(Map.Entry::getKey, Map.Entry::getValue);
    }
} 