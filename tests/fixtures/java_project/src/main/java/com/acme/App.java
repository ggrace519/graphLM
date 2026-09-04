package com.acme;

import com.acme.model.User;
import com.acme.service.UserService;
import com.acme.util.*;
import static com.acme.util.Helpers.now;
import java.util.List;

public class App {
    public static void main(String[] args) {
        UserService svc = new UserService();
        List<User> users = null;
        now();
    }
}
