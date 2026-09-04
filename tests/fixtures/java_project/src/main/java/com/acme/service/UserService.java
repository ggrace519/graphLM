package com.acme.service;

import com.acme.App;
import com.acme.model.User;

public class UserService {
    public User get() {
        return new User();
    }

    public App app() {
        return new App();
    }
}
