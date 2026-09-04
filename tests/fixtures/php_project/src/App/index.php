<?php
namespace App;

use App\Models\User;
use App\Services\UserService;
require "bootstrap.php";
include "./rel.php";
require_once "vendor/autoload.php";

$svc = new UserService();
$svc->load();
