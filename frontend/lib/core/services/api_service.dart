import 'dart:convert';
import 'dart:io';

class ApiService {
  const ApiService({this.baseUrl = 'http://127.0.0.1:8102'});
  final String baseUrl;

  Future<dynamic> request(
    String method,
    String path, {
    Object? body,
    Duration timeout = const Duration(minutes: 12),
  }) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
    try {
      final req = await client
          .openUrl(method, Uri.parse('$baseUrl$path'))
          .timeout(const Duration(seconds: 10));
      req.headers.set(HttpHeaders.acceptHeader, 'application/json');
      if (body != null) {
        req.headers.contentType = ContentType.json;
        req.write(jsonEncode(body));
      }
      final response = await req.close().timeout(timeout);
      final content = await utf8.decoder.bind(response).join().timeout(timeout);
      dynamic data;
      try {
        data = jsonDecode(content);
      } catch (_) {
        data = content;
      }
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final detail = data is Map
            ? (data['detail'] ?? data).toString()
            : content;
        throw Exception('HTTP ${response.statusCode}: $detail');
      }
      return data;
    } finally {
      client.close(force: true);
    }
  }

  Future<List<Map<String, dynamic>>> checkAmericanEnglish(String text) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 5);
    const wait = Duration(seconds: 30);
    try {
      final req = await client
          .postUrl(Uri.parse('http://127.0.0.1:8101/v2/check'))
          .timeout(wait);
      req.followRedirects = false;
      req.headers.set(
        HttpHeaders.contentTypeHeader,
        'application/x-www-form-urlencoded; charset=utf-8',
      );
      req.write('language=en-US&text=${Uri.encodeQueryComponent(text)}');
      final response = await req.close().timeout(wait);
      if (response.statusCode != 200) {
        throw StateError(
          'LanguageTool respondi\u00F3 HTTP ${response.statusCode}.',
        );
      }
      final data = jsonDecode(
        await utf8.decoder.bind(response).join().timeout(wait),
      );
      final matches = data is Map ? data['matches'] : null;
      if (matches is! List) {
        throw const FormatException(
          'LanguageTool no devolvi\u00F3 una lista de avisos.',
        );
      }
      return [
        for (final item in matches)
          if (item is Map) Map<String, dynamic>.from(item),
      ];
    } on SocketException {
      throw StateError('LanguageTool no responde en el puerto 8101.');
    } finally {
      client.close(force: true);
    }
  }

  Future<List<int>?> exportDocx(
    String pid,
    String mid,
    String vid,
    [String? originalPath]
  ) async {
    final file = originalPath == null ? null : File(originalPath);
    final length = file == null ? 0 : await file.length();
    if (length > 15 * 1024 * 1024) {
      throw StateError('El DOCX supera 15 MB.');
    }
    final boundary = 'liaDocx${DateTime.now().microsecondsSinceEpoch}';
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
    const limit = Duration(minutes: 2);
    try {
      final req = await client
          .postUrl(
            Uri.parse(
              '$baseUrl/api/projects/$pid/manuscripts/$mid/versions/$vid/export-docx',
            ),
          )
          .timeout(limit);
      if (file != null) {
        req.headers.set(
          HttpHeaders.contentTypeHeader,
          'multipart/form-data; boundary=$boundary',
        );
        req.write(
          '--$boundary\r\n'
          'Content-Disposition: form-data; name="file"; filename="original.docx"\r\n'
          'Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n',
        );
        await req.addStream(file.openRead()).timeout(limit);
        req.write('\r\n--$boundary--\r\n');
      }
      final res = await req.close().timeout(limit);
      if (res.statusCode != 200) {
        final detail = jsonDecode(
          await utf8.decoder.bind(res).join().timeout(limit),
        );
        if (res.statusCode == 409 && detail['detail'] == 'DOCX_TEMPLATE_REQUIRED') {
          return null;
        }
        throw StateError('${detail['detail']}');
      }
      return await res.expand((chunk) => chunk).toList().timeout(limit);
    } finally {
      client.close(force: true);
    }
  }

  Future<bool> isOnline() async {
    try {
      await request('GET', '/health', timeout: const Duration(seconds: 4));
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<List<dynamic>> projects() async =>
      (await request('GET', '/api/projects')) as List<dynamic>;
  Future<Map<String, dynamic>> createProject(String name) async =>
      Map<String, dynamic>.from(
        await request('POST', '/api/projects', body: {'name': name}),
      );
  Future<List<dynamic>> manuscripts(String pid) async =>
      (await request('GET', '/api/projects/$pid/manuscripts')) as List<dynamic>;
  Future<List<dynamic>> chapters(String pid, String mid) async =>
      (await request('GET', '/api/projects/$pid/manuscripts/$mid/chapters'))
          as List<dynamic>;
  Future<Map<String, dynamic>> chapter(
    String pid,
    String mid,
    int index,
  ) async => Map<String, dynamic>.from(
    await request('GET', '/api/projects/$pid/manuscripts/$mid/chapters/$index'),
  );
  Future<List<dynamic>> versions(String pid, String mid) async =>
      (await request('GET', '/api/projects/$pid/manuscripts/$mid/versions'))
          as List<dynamic>;
  Future<Map<String, dynamic>> version(
    String pid,
    String mid,
    String vid,
  ) async => Map<String, dynamic>.from(
    await request('GET', '/api/projects/$pid/manuscripts/$mid/versions/$vid'),
  );

  Future<Map<String, dynamic>> saveRevision(
    String pid,
    String mid,
    String vid,
    String text,
  ) async => Map<String, dynamic>.from(
    await request(
      'POST',
      '/api/projects/$pid/manuscripts/$mid/versions/$vid/revisions',
      body: {'translated_text': text},
    ),
  );

  Future<List<dynamic>> glossary(String pid) async =>
      (await request('GET', '/api/projects/$pid/glossary')) as List<dynamic>;
  Future<Map<String, dynamic>> addTerm(
    String pid,
    String source,
    String target,
  ) async => Map<String, dynamic>.from(
    await request(
      'POST',
      '/api/projects/$pid/glossary',
      body: {'source': source, 'target': target},
    ),
  );
  Future<Map<String, dynamic>> translationProgress(
    String pid,
    String mid,
    String jobId,
  ) async => Map<String, dynamic>.from(
    await request(
      'GET',
      '/api/projects/$pid/manuscripts/$mid/translation-progress/$jobId',
      timeout: const Duration(seconds: 4),
    ),
  );

  Future<Map<String, dynamic>> translate(
    String pid,
    String mid,
    int index, {
    String? model,
    String? jobId,
  }) async => Map<String, dynamic>.from(
    await request(
      'POST',
      '/api/projects/$pid/manuscripts/$mid/translate-chapter',
      body: {
        'chapter_index': index,
        'job_id': jobId,
        'model': model == null || model.trim().isEmpty ? null : model.trim(),
      },
      timeout: const Duration(minutes: 30),
    ),
  );

  Future<Map<String, dynamic>> upload(String pid, String path) async {
    final file = File(path);
    final length = await file.length();
    if (length > 15 * 1024 * 1024) throw Exception('El archivo supera 15 MB');
    final filename = file.uri.pathSegments.last;
    final boundary = 'lia${DateTime.now().microsecondsSinceEpoch}';
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
    try {
      final req = await client.postUrl(
        Uri.parse('$baseUrl/api/projects/$pid/manuscripts'),
      );
      req.headers.set(
        HttpHeaders.contentTypeHeader,
        'multipart/form-data; boundary=$boundary',
      );
      req.write(
        '--$boundary\r\nContent-Disposition: form-data; name="file"; filename="${filename.replaceAll('"', '_')}"\r\nContent-Type: application/octet-stream\r\n\r\n',
      );
      await req.addStream(file.openRead());
      req.write('\r\n--$boundary--\r\n');
      final response = await req.close().timeout(const Duration(minutes: 2));
      final text = await utf8.decoder.bind(response).join();
      final result = jsonDecode(text);
      if (response.statusCode != 201) {
        throw Exception('HTTP ${response.statusCode}: ${result['detail']}');
      }
      return Map<String, dynamic>.from(result);
    } finally {
      client.close(force: true);
    }
  }
}
