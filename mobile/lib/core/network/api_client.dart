import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../config/app_config.dart';

class ApiClient {
  ApiClient()
      : _dio = Dio(BaseOptions(
          baseUrl: AppConfig.apiBaseUrl,
          connectTimeout: const Duration(seconds: 15),
          receiveTimeout: const Duration(seconds: 20),
          headers: const {'Accept': 'application/json'},
        ));

  final Dio _dio;
  final FlutterSecureStorage _secureStorage = const FlutterSecureStorage();

  Future<Map<String, dynamic>> signIn({
    required String identifier,
    required String password,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/auth/login',
      data: {'identifier': identifier, 'password': password},
    );
    final data = response.data!;
    await _saveTokens(data);
    return currentIdentity();
  }

  Future<Map<String, dynamic>> restoreSession() async {
    final refreshToken = await _secureStorage.read(key: 'refresh_token');
    if (refreshToken == null) {
      throw StateError('No saved session');
    }
    final response = await _dio.post<Map<String, dynamic>>(
      '/auth/refresh',
      data: {'refresh_token': refreshToken},
    );
    await _saveTokens(response.data!);
    return currentIdentity();
  }

  Future<Map<String, dynamic>> currentIdentity() async {
    final token = await _secureStorage.read(key: 'access_token');
    if (token == null) {
      throw StateError('No access token');
    }
    final response = await _dio.get<Map<String, dynamic>>(
      '/identity/me',
      options: Options(headers: {'Authorization': 'Bearer $token'}),
    );
    return response.data!;
  }

  Future<void> signOut() async {
    final refreshToken = await _secureStorage.read(key: 'refresh_token');
    try {
      if (refreshToken != null) {
        await _dio.post<void>(
          '/auth/logout',
          data: {'refresh_token': refreshToken},
        );
      }
    } finally {
      await _secureStorage.deleteAll();
    }
  }

  Future<void> _saveTokens(Map<String, dynamic> data) async {
    final accessToken = data['access_token'] as String?;
    final refreshToken = data['refresh_token'] as String?;
    if (accessToken == null || refreshToken == null) {
      throw const FormatException('Authentication response did not contain tokens');
    }
    await _secureStorage.write(key: 'access_token', value: accessToken);
    await _secureStorage.write(key: 'refresh_token', value: refreshToken);
  }
}
