package com.chartink.webhook.service;

import org.json.JSONObject;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;

@Service
public class FyersHistoricalDataService {

    @Value("${fyers.app-id}")
    private String appId;

    private final FyersTokenGenerator tokenGenerator;
    private final HttpClient httpClient;
    private static final DateTimeFormatter DATE_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd");

    @Autowired
    public FyersHistoricalDataService(FyersTokenGenerator tokenGenerator) {
        this.tokenGenerator = tokenGenerator;
        this.httpClient = HttpClient.newHttpClient();
    }

    public JSONObject getHistoricalData(String symbol, String resolution, LocalDate fromDate, LocalDate toDate) throws Exception {
        String token = tokenGenerator.getToken();
        
        String url = String.format("https://api-t1.fyers.in/data/history?" +
            "symbol=%s&resolution=%s&date_format=1&range_from=%s&range_to=%s&cont_flag=1",
            URLEncoder.encode(symbol, StandardCharsets.UTF_8),
            resolution,
            fromDate.format(DATE_FORMATTER),
            toDate.format(DATE_FORMATTER)
        );

        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create(url))
            .header("Authorization", appId + ":" + token)
            .GET()
            .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        return new JSONObject(response.body());
    }
} 