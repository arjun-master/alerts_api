package com.chartink.webhook.controller;

import com.chartink.webhook.service.FyersAuthService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Mono;

@Slf4j
@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {
    private final FyersAuthService fyersAuthService;

    @GetMapping("/login-url")
    public String getLoginUrl() {
        log.info("Generating Fyers login URL");
        return fyersAuthService.getLoginUrl();
    }

    @PostMapping("/token")
    public Mono<String> generateToken(@RequestParam String authCode) {
        log.info("Generating access token for auth code: {}", authCode);
        return fyersAuthService.generateAccessToken(authCode);
    }
} 