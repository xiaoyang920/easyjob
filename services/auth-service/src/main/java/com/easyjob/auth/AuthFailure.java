package com.easyjob.auth;
public class AuthFailure extends RuntimeException {
    public final int status;
    public AuthFailure(int status,String message){super(message);this.status=status;}
}
