import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../config/app_config.dart';

class ApiClient {
  ApiClient()
      : _dio = Dio(
          BaseOptions(
            baseUrl: AppConfig.apiBaseUrl,
            connectTimeout: const Duration(seconds: 15),
            receiveTimeout: const Duration(seconds: 20),
            headers: const {'Accept': 'application/json'},
          ),
        ),
        _refreshDio = Dio(
          BaseOptions(
            baseUrl: AppConfig.apiBaseUrl,
            connectTimeout: const Duration(seconds: 15),
            receiveTimeout: const Duration(seconds: 20),
            headers: const {'Accept': 'application/json'},
          ),
        ) {
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final isAuthenticationRoute = options.path.endsWith('/auth/login') ||
              options.path.endsWith('/auth/refresh') ||
              options.path.endsWith('/auth/logout');
          if (!isAuthenticationRoute) {
            final token = await _secureStorage.read(key: 'access_token');
            if (token != null) {
              options.headers['Authorization'] = 'Bearer $token';
            }
          }
          handler.next(options);
        },
        onError: (error, handler) async {
          final options = error.requestOptions;
          final isAuthenticationRoute = options.path.endsWith('/auth/login') ||
              options.path.endsWith('/auth/refresh') ||
              options.path.endsWith('/auth/logout');
          if (error.response?.statusCode == 401 &&
              !isAuthenticationRoute &&
              options.extra['authRetry'] != true) {
            try {
              final token = await _refreshAccessToken();
              options.headers['Authorization'] = 'Bearer $token';
              options.extra['authRetry'] = true;
              final response = await _dio.fetch<dynamic>(options);
              handler.resolve(response);
              return;
            } catch (_) {
              // Preserve the original API error if refresh or the retry fails.
            }
          }
          handler.next(error);
        },
      ),
    );
  }

  final Dio _dio;
  final Dio _refreshDio;
  final FlutterSecureStorage _secureStorage = const FlutterSecureStorage();
  Future<String>? _refreshing;

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
    await _refreshAccessToken();
    return currentIdentity();
  }

  Future<String> _refreshAccessToken() async {
    final pending = _refreshing ??= _performRefresh();
    try {
      return await pending;
    } finally {
      if (identical(_refreshing, pending)) {
        _refreshing = null;
      }
    }
  }

  Future<String> _performRefresh() async {
    final refreshToken = await _secureStorage.read(key: 'refresh_token');
    if (refreshToken == null) {
      throw StateError('No saved session');
    }
    try {
      final response = await _refreshDio.post<Map<String, dynamic>>(
        '/auth/refresh',
        data: {'refresh_token': refreshToken},
      );
      final data = response.data;
      if (data == null || data['access_token'] is! String) {
        throw const FormatException('Refresh response did not contain an access token');
      }
      await _saveTokens(data);
      return data['access_token'] as String;
    } on DioException catch (error) {
      if (error.response?.statusCode == 401 ||
          error.response?.statusCode == 403) {
        await _secureStorage.deleteAll();
      }
      rethrow;
    }
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

  Future<List<Map<String, dynamic>>> listStocktakes(String organizationId) async {
    final token = await _requiredAccessToken();
    final response = await _dio.get<List<dynamic>>(
      '/stocktakes',
      options: Options(headers: {
        'Authorization': 'Bearer $token',
        'X-Organization-ID': organizationId,
      }),
    );
    return (response.data ?? const [])
        .cast<Map<String, dynamic>>();
  }

  Future<List<Map<String, dynamic>>> stocktakeScope(
    String organizationId,
    String stocktakeId,
  ) async {
    final token = await _requiredAccessToken();
    final response = await _dio.get<List<dynamic>>(
      '/stocktakes/$stocktakeId/scope',
      options: Options(headers: {
        'Authorization': 'Bearer $token',
        'X-Organization-ID': organizationId,
      }),
    );
    return (response.data ?? const [])
        .cast<Map<String, dynamic>>();
  }

  Future<List<Map<String, dynamic>>> myStocktakeObservations(
    String organizationId,
    String stocktakeId,
  ) async {
    final token = await _requiredAccessToken();
    final response = await _dio.get<List<dynamic>>(
      '/stocktakes/$stocktakeId/my-observations',
      options: Options(headers: {
        'Authorization': 'Bearer $token',
        'X-Organization-ID': organizationId,
      }),
    );
    return (response.data ?? const []).cast<Map<String, dynamic>>();
  }

  Future<List<Map<String, dynamic>>> listCountEvidence({
    required String organizationId,
    required String stocktakeId,
    required String observationId,
  }) async {
    final token = await _requiredAccessToken();
    final response = await _dio.get<List<dynamic>>(
      '/stocktakes/$stocktakeId/observations/$observationId/evidence',
      options: Options(headers: {
        'Authorization': 'Bearer $token',
        'X-Organization-ID': organizationId,
      }),
    );
    return (response.data ?? const []).cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> recordCount({
    required String organizationId,
    required String stocktakeId,
    required String itemId,
    required String quantity,
    required String unitCode,
    required String idempotencyKey,
  }) async {
    final token = await _requiredAccessToken();
    final response = await _dio.post<Map<String, dynamic>>(
      '/stocktakes/$stocktakeId/observations',
      data: {
        'item_id': itemId,
        'counted_quantity': quantity,
        'unit_code': unitCode,
        'idempotency_key': idempotencyKey,
      },
      options: Options(headers: {
        'Authorization': 'Bearer $token',
        'X-Organization-ID': organizationId,
      }),
    );
    return response.data!;
  }

  Future<void> uploadCountEvidence({
    required String organizationId,
    required String stocktakeId,
    required String observationId,
    required String filename,
    required String mediaType,
    required Uint8List bytes,
  }) async {
    final token = await _requiredAccessToken();
    await _dio.post<void>(
      '/stocktakes/$stocktakeId/observations/$observationId/evidence',
      queryParameters: {'filename': filename},
      data: bytes,
      options: Options(
        contentType: mediaType,
        headers: {
          'Authorization': 'Bearer $token',
          'X-Organization-ID': organizationId,
        },
      ),
    );
  }

  Future<void> submitStocktake({
    required String organizationId,
    required String stocktakeId,
  }) async {
    final token = await _requiredAccessToken();
    await _dio.post<void>(
      '/stocktakes/$stocktakeId/submit',
      data: const {},
      options: Options(headers: {
        'Authorization': 'Bearer $token',
        'X-Organization-ID': organizationId,
      }),
    );
  }

  Future<String> _requiredAccessToken() async {
    final token = await _secureStorage.read(key: 'access_token');
    if (token == null) throw StateError('No access token');
    return token;
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
      throw const FormatException(
        'Authentication response did not contain tokens',
      );
    }
    await _secureStorage.write(key: 'access_token', value: accessToken);
    await _secureStorage.write(key: 'refresh_token', value: refreshToken);
  }
}
