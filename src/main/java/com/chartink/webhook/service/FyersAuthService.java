package com.chartink.webhook.service;

import com.chartink.webhook.config.FyersConfig;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import okhttp3.*;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;

@Slf4j
@Service
@RequiredArgsConstructor
public class FyersAuthService {
    private final FyersConfig fyersConfig;
    private final OkHttpClient client;
    private final ObjectMapper objectMapper;
    private static final String FYERS_API_URL = "https://api.fyers.in/api/v2";
    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");

    public String getLoginUrl() {
        try {
            String appId = fyersConfig.getAppId();
            String redirectUri = fyersConfig.getRedirectUri();
            String state = generateState(appId, redirectUri);
            
            return String.format(
                "https://api.fyers.in/api/v2/generate-authcode?" +
                "client_id=%s&redirect_uri=%s&response_type=code&state=%s",
                appId, redirectUri, state
            );
        } catch (Exception e) {
            log.error("Error generating login URL: {}", e.getMessage());
            throw new RuntimeException("Failed to generate login URL", e);
        }
    }

    public Mono<String> generateAccessToken(String authCode) {
        String appIdHash = generateAppIdHash();
        
        return Mono.fromCallable(() -> {
            String requestBody = String.format(
                "{\"grant_type\":\"authorization_code\",\"appIdHash\":\"%s\",\"code\":\"%s\"}",
                appIdHash, authCode
            );

            Request request = new Request.Builder()
                .url(FYERS_API_URL + "/validate-authcode")
                .post(RequestBody.create(requestBody, JSON))
                .build();

            try (Response response = client.newCall(request).execute()) {
                String responseBody = response.body().string();
                JsonNode jsonResponse = objectMapper.readTree(responseBody);
                
                if (!response.isSuccessful()) {
                    log.error("Error response from Fyers: {}", responseBody);
                    throw new RuntimeException("Failed to generate access token: " + jsonResponse.path("message").asText());
                }

                if (!"ok".equals(jsonResponse.path("s").asText())) {
                    throw new RuntimeException("Error from Fyers: " + jsonResponse.path("message").asText());
                }

                String accessToken = jsonResponse.path("access_token").asText();
                log.info("Successfully generated access token");
                return accessToken;
            }
        });
    }

    private String generateState(String appId, String redirectUri) throws Exception {
        String stateData = appId + ":" + redirectUri;
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] hash = digest.digest(stateData.getBytes(StandardCharsets.UTF_8));
        return Base64.getUrlEncoder().withoutPadding().encodeToString(hash);
    }

    private String generateAppIdHash() {
        try {
            String appId = fyersConfig.getAppId();
            String secretId = fyersConfig.getSecretId();
            String data = appId + ":" + secretId;
            
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(data.getBytes(StandardCharsets.UTF_8));
            return Base64.getUrlEncoder().withoutPadding().encodeToString(hash);
        } catch (Exception e) {
            log.error("Error generating app ID hash: {}", e.getMessage());
            throw new RuntimeException("Failed to generate appIdHash", e);
        }
    }
} 