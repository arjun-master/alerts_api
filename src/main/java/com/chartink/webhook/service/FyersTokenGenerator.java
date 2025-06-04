package com.chartink.webhook.service;

import org.json.JSONObject;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.UUID;

@Service
public class FyersTokenGenerator {

    @Value("${fyers.app-id}")
    private String appId;

    @Value("${fyers.secret-id}")
    private String secretKey;

    @Value("${fyers.redirect-uri}")
    private String redirectUri;

    @Value("${fyers.auth-code}")
    private String authCode;

    private static final String TOKEN_FILE = "fyers_token.txt";
    private final HttpClient httpClient = HttpClient.newHttpClient();

    public String getToken() throws Exception {
        String token = readFile();
        if (token == null || !isTokenValid(token)) {
            token = generateNewToken();
            if (!isTokenValid(token)) {
                throw new RuntimeException("Failed to generate valid token");
            }
            writeFile(token);
        }
        return token;
    }

    private String generateNewToken() throws Exception {
        // Step 1: Generate auth code URL
        String state = UUID.randomUUID().toString();
        String authUrl = String.format(
            "https://api-t1.fyers.in/api/v3/generate-authcode?" +
            "client_id=%s&redirect_uri=%s&response_type=code&state=%s&scope=openid",
            URLEncoder.encode(appId, StandardCharsets.UTF_8),
            URLEncoder.encode(redirectUri, StandardCharsets.UTF_8),
            state
        );

        if ("YOUR_AUTH_CODE".equals(authCode)) {
            System.out.println("Please open this URL in your browser and complete the login process:");
            System.out.println(authUrl);
            System.out.println("\nAfter login, you'll be redirected to: " + redirectUri);
            System.out.println("Copy the 'auth_code' parameter from the redirect URL and set it in application.properties");
            throw new RuntimeException("Auth code not configured in application.properties");
        }

        // Step 2: Validate auth code
        String appIdHash = generateAppIdHash();
        JSONObject requestBody = new JSONObject()
            .put("grant_type", "authorization_code")
            .put("appIdHash", appIdHash)
            .put("code", authCode)
            .put("client_id", appId)
            .put("scope", "openid");

        System.out.println("Request Body: " + requestBody.toString(2));

        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create("https://api-t1.fyers.in/api/v3/validate-authcode"))
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .header("User-Agent", "Mozilla/5.0")
            .POST(HttpRequest.BodyPublishers.ofString(requestBody.toString()))
            .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        System.out.println("Response: " + response.body());
        JSONObject jsonResponse = new JSONObject(response.body());

        if (!"ok".equals(jsonResponse.getString("s"))) {
            throw new RuntimeException("Failed to validate auth code: " + jsonResponse.toString(2));
        }

        return jsonResponse.getString("access_token");
    }

    private String generateAppIdHash() throws Exception {
        // Extract app ID from auth code JWT token
        String[] parts = authCode.split("\\.");
        String payload = new String(Base64.getUrlDecoder().decode(parts[1]));
        System.out.println("JWT Payload: " + payload);
        JSONObject payloadJson = new JSONObject(payload);
        String appIdFromToken = payloadJson.getString("app_id");
        System.out.println("App ID from token: " + appIdFromToken);

        // Generate hash using app ID from token
        String data = appIdFromToken + ":" + secretKey;
        System.out.println("Data for hash: " + data);
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] hash = digest.digest(data.getBytes(StandardCharsets.UTF_8));
        String base64 = Base64.getUrlEncoder().withoutPadding().encodeToString(hash);
        System.out.println("Generated App ID Hash: " + base64);
        return base64;
    }

    private boolean isTokenValid(String token) {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create("https://api-t1.fyers.in/api/v3/profile"))
                .header("Authorization", appId + ":" + token)
                .GET()
                .build();

            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            JSONObject json = new JSONObject(response.body());
            return "ok".equals(json.getString("s"));
        } catch (Exception e) {
            return false;
        }
    }

    private String readFile() {
        try {
            Path path = Paths.get(TOKEN_FILE);
            if (Files.exists(path)) {
                return Files.readString(path).trim();
            }
        } catch (IOException e) {
            // Ignore and return null
        }
        return null;
    }

    private void writeFile(String token) throws IOException {
        Files.writeString(Paths.get(TOKEN_FILE), token);
    }
} 