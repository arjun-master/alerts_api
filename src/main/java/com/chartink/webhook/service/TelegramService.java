package com.chartink.webhook.service;

import com.chartink.webhook.model.WebhookData;
import io.github.resilience4j.ratelimiter.RateLimiter;
import io.github.resilience4j.ratelimiter.RateLimiterConfig;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.time.Duration;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Semaphore;
import java.util.stream.Collectors;

@Slf4j
@Service
public class TelegramService {

    private final WebClient webClient;
    private final String chatId;
    private final Semaphore rateLimitSemaphore;
    private final StockAnalysisService stockAnalysisService;
    private static final int MAX_REQUESTS_PER_SECOND = 25; // Setting slightly lower than Telegram's limit for safety

    public TelegramService(
            @Value("${telegram.bot.token}") String botToken,
            @Value("${telegram.chat.id}") String chatId,
            StockAnalysisService stockAnalysisService) {
        this.chatId = chatId;
        this.stockAnalysisService = stockAnalysisService;
        this.webClient = WebClient.builder()
                .baseUrl("https://api.telegram.org/bot" + botToken)
                .defaultHeader(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                .build();

        this.rateLimitSemaphore = new Semaphore(MAX_REQUESTS_PER_SECOND);
        
        log.info("TelegramService initialized with chat ID: {} and rate limit: {} requests per second", 
                chatId, MAX_REQUESTS_PER_SECOND);

        // Start the rate limit replenishment thread
        startRateLimitReplenishment();
    }

    private void startRateLimitReplenishment() {
        Thread replenishThread = new Thread(() -> {
            while (true) {
                try {
                    Thread.sleep(1000); // Wait for 1 second
                    int permitsToAdd = MAX_REQUESTS_PER_SECOND - rateLimitSemaphore.availablePermits();
                    if (permitsToAdd > 0) {
                        rateLimitSemaphore.release(permitsToAdd);
                        log.debug("Replenished {} rate limit permits", permitsToAdd);
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    break;
                }
            }
        });
        replenishThread.setDaemon(true);
        replenishThread.setName("telegram-rate-limit-replenisher");
        replenishThread.start();
    }

    public Mono<String> sendMessage(WebhookData data) {
        return getStockReturnsMap(data)
                .flatMap(stockReturns -> {
                    String message = formatMessage(data, stockReturns);
                    Instant start = Instant.now();

                    return Mono.just(message)
                            .publishOn(Schedulers.boundedElastic())
                            .flatMap(msg -> acquireRateLimit()
                                .flatMap(acquired -> {
                                    log.info("Sending message to Telegram for scan: {}, stocks: {}", 
                                            data.getScanName(), data.getStocks());
                                    
                                    return webClient.post()
                                            .uri("/sendMessage")
                                            .bodyValue(new TelegramRequest(chatId, msg))
                                            .retrieve()
                                            .bodyToMono(String.class)
                                            .timeout(Duration.ofSeconds(10))
                                            .doOnSuccess(response -> {
                                                Duration duration = Duration.between(start, Instant.now());
                                                log.info("Message sent successfully to Telegram in {} ms. Scan: {}, Stocks: {}", 
                                                        duration.toMillis(), data.getScanName(), data.getStocks());
                                            })
                                            .doOnError(error -> {
                                                Duration duration = Duration.between(start, Instant.now());
                                                log.error("Error sending message to Telegram in {} ms. Scan: {}, Error: {}", 
                                                        duration.toMillis(), data.getScanName(), error.getMessage());
                                            })
                                            .doFinally(signalType -> rateLimitSemaphore.release());
                                }))
                            .retryWhen(reactor.util.retry.Retry.backoff(3, Duration.ofSeconds(1))
                                    .maxBackoff(Duration.ofSeconds(10))
                                    .filter(throwable -> throwable.getMessage() != null && 
                                            throwable.getMessage().contains("429"))); // Only retry on rate limit errors
                });
    }

    private Mono<Map<String, StockAnalysisService.StockReturn>> getStockReturnsMap(WebhookData data) {
        String[] stocks = data.getStocks().split(",\\s*");
        return stockAnalysisService.getStockReturnsMap(stocks);
    }

    private String formatMessage(WebhookData data, Map<String, StockAnalysisService.StockReturn> stockReturns) {
        StringBuilder message = new StringBuilder();
        message.append("🔔 <b>").append(escapeHtml(data.getAlertName())).append("</b>\n");
        message.append("📊 <b>").append(escapeHtml(data.getScanName())).append("</b>\n\n");
        
        String[] stocks = data.getStocks().split(",\\s*");
        String[] prices = data.getTriggerPrices().split(",\\s*");
        
        message.append("<b>Stock Analysis:</b>\n");
        for (int i = 0; i < stocks.length; i++) {
            String stock = stocks[i].trim();
            String price = i < prices.length ? prices[i].trim() : "N/A";
            StockAnalysisService.StockReturn returns = stockReturns.getOrDefault(stock, 
                    new StockAnalysisService.StockReturn(0.0, 0.0, 0.0));
            
            message.append("📈 <b>").append(escapeHtml(stock)).append("</b> @ ₹")
                  .append(escapeHtml(price)).append("\n");
            
            message.append(String.format("   Returns: 1D: %+.2f%% | 3D: %+.2f%% | 1W: %+.2f%%\n\n",
                    returns.oneDayReturn(), returns.threeDayReturn(), returns.oneWeekReturn()));
        }
        
        message.append("🕒 <b>Triggered At:</b> ")
              .append(escapeHtml(data.getTriggeredAt()));
        
        return message.toString();
    }

    private String escapeHtml(String text) {
        if (text == null) return "";
        return text.replace("&", "&amp;")
                  .replace("<", "&lt;")
                  .replace(">", "&gt;")
                  .replace("\"", "&quot;");
    }

    private Mono<Boolean> acquireRateLimit() {
        return Mono.fromCallable(() -> {
            boolean acquired = rateLimitSemaphore.tryAcquire(Duration.ofSeconds(30).toMillis(), java.util.concurrent.TimeUnit.MILLISECONDS);
            if (!acquired) {
                throw new RuntimeException("Rate limit exceeded, please try again later");
            }
            return true;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    public Mono<String> sendCustomMessage(String message) {
        Instant start = Instant.now();
        return Mono.just(message)
                .publishOn(Schedulers.boundedElastic())
                .flatMap(msg -> acquireRateLimit()
                    .flatMap(acquired -> {
                        log.info("Sending custom message to Telegram");
                        return webClient.post()
                                .uri("/sendMessage")
                                .bodyValue(new TelegramRequest(chatId, msg))
                                .retrieve()
                                .bodyToMono(String.class)
                                .timeout(Duration.ofSeconds(10))
                                .doOnSuccess(response -> {
                                    Duration duration = Duration.between(start, Instant.now());
                                    log.info("Custom message sent successfully to Telegram in {} ms.", duration.toMillis());
                                })
                                .doOnError(error -> {
                                    Duration duration = Duration.between(start, Instant.now());
                                    log.error("Error sending custom message to Telegram in {} ms. Error: {}", duration.toMillis(), error.getMessage());
                                })
                                .doFinally(signalType -> rateLimitSemaphore.release());
                    }))
                .retryWhen(reactor.util.retry.Retry.backoff(3, Duration.ofSeconds(1))
                        .maxBackoff(Duration.ofSeconds(10))
                        .filter(throwable -> throwable.getMessage() != null &&
                                throwable.getMessage().contains("429")));
    }

    private record TelegramRequest(String chat_id, String text, String parse_mode) {
        TelegramRequest(String chat_id, String text) {
            this(chat_id, text, "HTML");
        }
    }
} 