package com.easyjob.service;


public interface EmailService {
    void sendVerificationCode(String email, String code);
}
