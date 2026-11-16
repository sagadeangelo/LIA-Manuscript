import 'dart:typed_data' as docx_bytes;
import 'dart:convert' as dictionary_json;
import 'dart:io' as dictionary_io;
import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:file_selector/file_selector.dart';

import '../core/services/api_service.dart';
import '../core/theme/lia_theme.dart';

class EditorScreen extends StatefulWidget {
  const EditorScreen({
    super.key,
    required this.projectId,
    required this.projectName,
  });
  final String projectId, projectName;
  @override
  State<EditorScreen> createState() => _EditorScreenState();
}

class _EditorScreenState extends State<EditorScreen> {
  final api = const ApiService();
  int translationPercent = 0;
  Timer? progressTimer;
  final original = TextEditingController();
  final translated = TextEditingController();
  final sourceTerm = TextEditingController();
  final targetTerm = TextEditingController();
  List<String> installedModels = [];
  String? selectedModel;
  bool loadingModels = false;
  String? modelsError;
  int completedSegments = 0;
  int totalSegments = 0;
  Duration translationElapsed = Duration.zero;

  Future<void> refreshModels() async {
    if (loadingModels || translating) {
      return;
    }
    setState(() {
      loadingModels = true;
      modelsError = null;
    });
    final wait = const Duration(seconds: 5);
    final client = dictionary_io.HttpClient()..connectionTimeout = wait;
    try {
      final request = await client.getUrl(
        Uri.parse('http://127.0.0.1:11434/api/tags'),
      ).timeout(wait);
      request.followRedirects = false;
      final response = await request.close().timeout(wait);
      if (response.statusCode != 200) {
        throw StateError('Ollama devolvió HTTP ${response.statusCode}.');
      }
      final body = await dictionary_json.utf8.decoder
          .bind(response).join().timeout(wait);
      final data = dictionary_json.jsonDecode(body);
      if (data is! Map || data['models'] is! List) {
        throw const FormatException('Catálogo de Ollama inválido.');
      }
      final names = <String>{};
      for (final item in data['models'] as List) {
        if (item is Map) {
          final name = item['name'] ?? item['model'];
          if (name is String && name.trim().isNotEmpty) {
            names.add(name.trim());
          }
        }
      }
      if (mounted) {
        setState(() {
          installedModels = names.toList()..sort();
          if (!installedModels.contains(selectedModel)) {
            selectedModel = installedModels.length == 1
                ? installedModels.single : null;
          }
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() => modelsError = 'No se pudo consultar Ollama. $error');
      }
    } finally {
      client.close(force: true);
      if (mounted) {
        setState(() => loadingModels = false);
      }
    }
  }
  List<dynamic> manuscripts = [], chapters = [], versions = [], terms = [];
  String? manuscriptId;
  int chapterIndex = 0;
  bool busy = false;
  bool translating = false;
  String status = 'Selecciona o importa un manuscrito';
  @override
  void initState() {
    super.initState();
    unawaited(refreshModels());
    loadManuscripts();
  }

  @override
  void dispose() {
    progressTimer?.cancel();
    original.dispose();
    translated.dispose();
    sourceTerm.dispose();
    targetTerm.dispose();
    super.dispose();
  }

  Future<void> task(Future<void> Function() action) async {
    if (busy) return;
    setState(() => busy = true);
    try {
      await action();
    } catch (e) {
      if (mounted) {
        setState(() => status = 'Error: $e');
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> loadManuscripts() async => task(() async {
    final found = await api.manuscripts(widget.projectId);
    if (!mounted) return;
    setState(() => manuscripts = found);
    if (found.isNotEmpty) {
      await selectManuscript('${found.first['id']}');
    }
  });
  Future<void> importFile() async {
    const type = XTypeGroup(label: 'Manuscritos', extensions: ['txt', 'docx']);
    final selected = await openFile(acceptedTypeGroups: [type]);
    if (selected == null) return;
    await task(() async {
      setState(() => status = 'Importando ${selected.name}...');
      final uploaded = await api.upload(widget.projectId, selected.path);
      final found = await api.manuscripts(widget.projectId);
      if (!mounted) return;
      setState(() => manuscripts = found);
      await selectManuscript('${uploaded['id']}');
    });
  }

  Future<void> selectManuscript(String mid) async {
    final found = await api.chapters(widget.projectId, mid);
    final glossary = await api.glossary(widget.projectId);
    if (!mounted) return;
    setState(() {
      manuscriptId = mid;
      chapters = found;
      terms = glossary;
      chapterIndex = 0;
      versions = [];
      loadedVersionId = null;
      original.clear();
      translated.clear();
    });
    if (found.isNotEmpty) await selectChapter(0);
  }

  Future<void> selectChapter(int index) async {
    final mid = manuscriptId;
    if (mid == null) return;
    final detail = await api.chapter(widget.projectId, mid, index);
    final history = await api.versions(widget.projectId, mid);
    final relevant = history
        .where((v) => v is Map && v['chapter_index'] == index)
        .toList();
    if (!mounted) return;
    setState(() {
      chapterIndex = index;
      original.text = '${detail['text']}';
      translated.clear();
      loadedVersionId = null;
      translationPercent = 0;
      versions = relevant;
      status = 'Capítulo cargado';
    });
    if (relevant.isNotEmpty) await loadVersion('${relevant.first['id']}');
  }

  static Color englishMarkColor(Map<String, dynamic> match) {
    final rule = match['rule'];
    final category = rule is Map ? rule['category'] : null;
    final id = category is Map ? category['id'] : null;
    switch (id) {
      case 'TYPOS':
      case 'PUNCTUATION':
      case 'CASING':
        return const Color(0xFFFFF54F);
      case 'GRAMMAR':
        return const Color(0xFF75FF80);
      default:
        return const Color(0xFFD5A1FF);
    }
  }

  List<TextSpan> englishMarkedSpans(
    String text,
    List<Map<String, dynamic>> matches,
  ) {
    final spans = <TextSpan>[];
    var cursor = 0;
    for (final match in matches) {
      final start = match['offset'] as int;
      final end = start + (match['length'] as int);
      if (start < cursor) {
        continue;
      }
      spans.add(TextSpan(text: text.substring(cursor, start)));
      spans.add(
        TextSpan(
          text: text.substring(start, end),
          style: TextStyle(
            color: Colors.black,
            backgroundColor: englishMarkColor(match),
          ),
        ),
      );
      cursor = end;
    }
    spans.add(TextSpan(text: text.substring(cursor)));
    return spans;
  }

  dictionary_io.File englishDictionaryFile() {
    final env = dictionary_io.Platform.environment;
    final base = env['LOCALAPPDATA'] ?? env['USERPROFILE'];
    if (base == null || base.isEmpty) {
      throw StateError('No se encontr\u00F3 la carpeta local del usuario.');
    }
    final separator = dictionary_io.Platform.pathSeparator;
    return dictionary_io.File(
      '$base${separator}LIA-Manuscript${separator}dictionary-en-US.json',
    );
  }

  Set<String> readEnglishDictionary(dictionary_io.File file) {
    if (!file.existsSync()) {
      return <String>{};
    }
    final content = dictionary_json.jsonDecode(file.readAsStringSync());
    if (content is! List || content.any((entry) => entry is! String)) {
      throw const FormatException(
        'El diccionario local no tiene el formato esperado.',
      );
    }
    return content.cast<String>().toSet();
  }

  String englishDictionaryKey(String word) {
    return word.trim().toLowerCase()
        .replaceAll('n\u0303', 'ñ')
        .replaceAll(RegExp(r'[áàâäãå]'), 'a')
        .replaceAll(RegExp(r'[éèêë]'), 'e')
        .replaceAll(RegExp(r'[íìîï]'), 'i')
        .replaceAll(RegExp(r'[óòôöõ]'), 'o')
        .replaceAll(RegExp(r'[úùûü]'), 'u')
        .replaceAll(RegExp(r'[\u0300\u0301\u0302\u0303\u0308\u030A]'), '');
  }

  bool isEnglishSpellingWarning(Map<String, dynamic> match) {
    final rule = match['rule'];
    if (rule is! Map) {
      return false;
    }
    final category = rule['category'];
    return rule['issueType'] == 'misspelling' ||
        (category is Map && category['id'] == 'TYPOS');
  }

  Future<void> reviewAmericanEnglish() async {
    final mid = manuscriptId;
    final vid = loadedVersionId;
    final index = chapterIndex;
    if (mid == null || vid == null) {
      return;
    }

    await task(() async {
      final version = await api.version(widget.projectId, mid, vid);
      if (!mounted || version['chapter_index'] != index) {
        return;
      }
      final original = version['translated_text'] as String;
      var draft = original;
      final dictionaryFile = englishDictionaryFile();
      final dictionary = readEnglishDictionary(dictionaryFile);
      final dictionaryKeys = dictionary.map(englishDictionaryKey).toSet();

      List<Map<String, dynamic>> visibleMatches(
        String text, List<Map<String, dynamic>> found,
      ) => found.where((match) {
              final start = match['offset'];
              final length = match['length'];
              if (start is int &&
                  length is int &&
                  start >= 0 &&
                  length > 0 &&
                  start + length <= text.length &&
                  isEnglishSpellingWarning(match) &&
                  dictionaryKeys.contains(englishDictionaryKey(text.substring(start, start + length)))) {
                return false;
              }
              return start is int &&
                  length is int &&
                  start >= 0 &&
                  length >= 0 &&
                  start + length <= text.length;
            }).toList()..sort(
              (a, b) => (a['offset'] as int).compareTo(b['offset'] as int),
            );

      var found = await api.checkAmericanEnglish(draft);
      if (!mounted) {
        return;
      }
      var updating = false;
      String? reviewError;
      final accepted = await showDialog<bool>(
          context: context,
          builder: (dialogContext) => StatefulBuilder(
            builder: (context, refresh) {
              final matches = visibleMatches(draft, found);

              void saveDictionaryWord(String word) {
                final updated = {...dictionary, word}.toList()..sort();
                dictionaryFile.parent.createSync(recursive: true);
                dictionaryFile.writeAsStringSync(
                  dictionary_json.jsonEncode(updated), flush: true,
                );
                dictionary.add(word);
                dictionaryKeys.add(englishDictionaryKey(word));
              }

              Future<void> applyReplacement(
                String updated, {String? dictionaryWord}
              ) async {
                if (updating || updated == draft) {
                  return;
                }
                refresh(() {
                  updating = true;
                  reviewError = null;
                });
                try {
                  final checked = await api.checkAmericanEnglish(updated);
                  if (!dialogContext.mounted) {
                    return;
                  }
                  if (dictionaryWord != null) {
                    saveDictionaryWord(dictionaryWord);
                  }
                  refresh(() {
                    draft = updated;
                    found = checked;
                  });
                } catch (error) {
                  if (dialogContext.mounted) {
                    refresh(() => reviewError = 'No se pudo actualizar la revisión: $error');
                  }
                } finally {
                  if (dialogContext.mounted) {
                    refresh(() => updating = false);
                  }
                }
              }

              void addToDictionary(String word) {
                try {
                  saveDictionaryWord(word);
                  refresh(() => reviewError = null);
                } catch (error) {
                  refresh(() => reviewError = 'No se pudo guardar el diccionario: $error');
                }
              }

              return AlertDialog(
            title: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Revisión de inglés americano'),
                if (updating) const LinearProgressIndicator(),
                if (reviewError != null)
                  Text(reviewError!, style: TextStyle(color: Theme.of(context).colorScheme.error, fontSize: 14)),
              ],
            ),
            content: SizedBox(
              width: 960,
              height: 520,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: SingleChildScrollView(
                      child: SelectableText.rich(
                        TextSpan(children: englishMarkedSpans(draft, matches)),
                      ),
                    ),
                  ),
                  const SizedBox(width: 20),
                  Expanded(
                    child: matches.isEmpty
                        ? const Text('LanguageTool no encontr\u00F3 avisos.')
                        : ListView.builder(
                            itemCount: matches.length,
                            itemBuilder: (context, index) {
                              final match = matches[index];
                              final start = match['offset'] as int;
                              final end = start + (match['length'] as int);
                              final replacements = match['replacements'];
                              final rule = match['rule'];
                              final category = rule is Map
                                  ? rule['category']
                                  : null;
                              return Padding(
                                padding: const EdgeInsets.only(bottom: 16),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      start == end
                                          ? 'Inserci\u00F3n en posici\u00F3n $start'
                                          : draft.substring(start, end),
                                      style: TextStyle(
                                        color: Colors.black,
                                        backgroundColor: englishMarkColor(
                                          match,
                                        ),
                                      ),
                                    ),
                                    if (category is Map)
                                      Text(
                                        '${category['name'] ?? category['id']}',
                                      ),
                                    Text('${match['message'] ?? ''}'),
                                    if (start < end &&
                                        isEnglishSpellingWarning(match))
                                      TextButton.icon(
                                        icon: const Icon(
                                          Icons.bookmark_add_outlined,
                                        ),
                                        label: const Text(
                                          'Agregar al diccionario',
                                        ),
                                        onPressed: updating ? null : () => addToDictionary(draft.substring(start, end)),
                                      ),
                                    TextButton.icon(
                                      icon: const Icon(Icons.edit_outlined),
                                      label: const Text('Editar fragmento'),
                                      onPressed: updating ? null : () async {
                                        var replacement = draft.substring(
                                          start,
                                          end,
                                        );
                                        final edited = await showDialog<String>(
                                          context: dialogContext,
                                          builder: (editContext) => AlertDialog(
                                            title: const Text(
                                              'Editar fragmento',
                                            ),
                                            content: TextFormField(
                                              initialValue: replacement,
                                              autofocus: true,
                                              decoration: const InputDecoration(
                                                labelText:
                                                    'Texto en ingl\u00E9s',
                                              ),
                                              onChanged: (value) =>
                                                  replacement = value,
                                              onFieldSubmitted: (value) =>
                                                  Navigator.pop(
                                                    editContext,
                                                    value,
                                                  ),
                                            ),
                                            actions: [
                                              TextButton(
                                                onPressed: () =>
                                                    Navigator.pop(editContext),
                                                child: const Text('Cancelar'),
                                              ),
                                              FilledButton(
                                                onPressed: () => Navigator.pop(
                                                  editContext,
                                                  replacement,
                                                ),
                                                child: const Text(
                                                  'Aplicar al borrador',
                                                ),
                                              ),
                                            ],
                                          ),
                                        );
                                        if (!dialogContext.mounted ||
                                            edited == null) {
                                          return;
                                        }
                                        if (edited ==
                                            draft.substring(start, end)) {
                                          return;
                                        }
                                        final word = edited.trim();
                                        final addWord = isEnglishSpellingWarning(match) &&
                                            RegExp(r"^[\p{L}\p{M}]+(?:[-’'][\p{L}\p{M}]+)*$", unicode: true)
                                                .hasMatch(word);
                                        await applyReplacement(
                                          draft.replaceRange(start, end, edited),
                                          dictionaryWord: addWord ? word : null,
                                        );
                                      },
                                    ),
                                    if (replacements is List)
                                      Wrap(
                                        spacing: 8,
                                        children: [
                                          for (final item in replacements.take(
                                            5,
                                          ))
                                            if (item is Map &&
                                                item['value'] is String)
                                              ActionChip(
                                                label: Text(
                                                  item['value'] == ''
                                                      ? 'Eliminar'
                                                      : item['value'] as String,
                                                ),
                                                onPressed: updating ? null : () => applyReplacement(
                                                  draft.replaceRange(start, end, item['value'] as String),
                                                ),
                                              ),
                                        ],
                                      ),
                                  ],
                                ),
                              );
                            },
                          ),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: const Text('Cancelar'),
              ),
              FilledButton(
                onPressed: updating || draft == original
                    ? null
                    : () => Navigator.pop(dialogContext, true),
                child: const Text('Guardar versi\u00F3n revisada'),
              ),
            ],
              );
            },
          ),
        );
        if (!mounted || accepted != true) {
          return;
        }

        final saved = await api.saveRevision(widget.projectId, mid, vid, draft);
        if (!mounted) {
          return;
        }
        await loadVersion(saved['id'] as String);
        if (!mounted) {
          return;
        }
        final history = await api.versions(widget.projectId, mid);
        if (!mounted) {
          return;
        }
        setState(() {
          versions = history
              .where((v) => v is Map && v['chapter_index'] == index)
              .toList();
          status = 'Versi\u00F3n revisada guardada';
        });
    });
  }

  Future<void> exportSavedDocx() async {
    final mid = manuscriptId;
    final vid = loadedVersionId;
    if (mid == null || vid == null) {
      return;
    }
    await task(() async {
      const word = XTypeGroup(label: 'Word DOCX', extensions: ['docx']);
      final template = await openFile(acceptedTypeGroups: [word]);
      if (template == null || !mounted) {
        return;
      }
      final bytes = await api.exportDocx(
        widget.projectId,
        mid,
        vid,
        template.path,
      );
      if (!mounted) {
        return;
      }
      final originalName = template.name.replaceFirst(
        RegExp(r'\.docx$', caseSensitive: false), '',
      );
      final stamp = DateTime.now().toIso8601String().replaceAll(':', '-');
      final location = await getSaveLocation(
        acceptedTypeGroups: [word],
        suggestedName: '${originalName}_EN-US_${vid.split('-').first}_$stamp.docx',
      );
      if (location == null || !mounted) {
        return;
      }
      final target = location.path.toLowerCase().endsWith('.docx')
          ? location.path
          : '${location.path}.docx';
      if (await dictionary_io.File(target).exists()) {
        throw StateError(
          'Ese archivo ya existe. Elige otro nombre para la copia.',
        );
      }
      await XFile.fromData(bytesForDocx(bytes)).saveTo(target);
      if (mounted) {
        setState(() => status = 'DOCX exportado: $target');
      }
    });
  }

  docx_bytes.Uint8List bytesForDocx(List<int> bytes) =>
      docx_bytes.Uint8List.fromList(bytes);

  String? loadedVersionId;

  Future<void> reviewVersion({bool onlyWarnings = false}) async {
    final mid = manuscriptId;
    final vid = loadedVersionId;
    final index = chapterIndex;
    if (mid == null || vid == null) return;

    await task(() async {
      final version = await api.version(widget.projectId, mid, vid);
      if (!mounted || version['chapter_index'] != index) return;

      final source = version['source_text'] as String;
      final target = version['translated_text'] as String;
      final sourceLines = source
          .split(RegExp(r'\r?\n'))
          .where((line) => line.trim().isNotEmpty)
          .toList();
      final targetLines = target.split('\n');
      final rows = [
        for (var i = 0; i < targetLines.length; i++)
          if (targetLines[i].trim().isNotEmpty) i,
      ];
      final warnings = <Map>[
        if (version['warnings'] is List)
          for (final item in version['warnings'] as List)
            if (item is Map) item,
      ];
      String warningText(Map warning) {
        return '${warning['message'] ?? warning['detail'] ?? warning['type'] ?? warning['code'] ?? warning}';
      }

      final headingPattern = RegExp(
        r'^(dedicatoria|prefacio)$',
        caseSensitive: false,
      );
      final firstHeading = sourceLines.indexWhere(
        (line) => headingPattern.hasMatch(line.trim()),
      );
      final proseRows = <int>[
        for (var i = firstHeading + 1; i < sourceLines.length; i++)
          if (!headingPattern.hasMatch(sourceLines[i].trim())) i,
      ];
      final isKnownPreface =
          firstHeading == 4 &&
          sourceLines[1].trim().startsWith('Copyright ') &&
          sourceLines[2].trim().startsWith('ISBN:') &&
          sourceLines[3].trim() == 'Kindle Direct Publishing';
      final canMap =
          isKnownPreface &&
          sourceLines.length == rows.length &&
          proseRows.every((i) => sourceLines[i].length < 2000) &&
          version['chapter_index'] == 0;
      final byRow = <int, List<Map>>{};
      final unassigned = <Map>[];

      for (final warning in warnings) {
        final segment = int.tryParse('${warning['segment']}');
        if (canMap &&
            segment != null &&
            segment >= 1 &&
            segment <= proseRows.length) {
          (byRow[proseRows[segment - 1]] ??= []).add(warning);
        } else {
          unassigned.add(warning);
        }
      }

      if (onlyWarnings && (warnings.isEmpty || unassigned.isNotEmpty)) {
        await showDialog<void>(
          context: context,
          builder: (dialogContext) => AlertDialog(
            title: const Text('Avisos de la versi\u00F3n'),
            content: SizedBox(
              width: 640,
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (warnings.isEmpty)
                      const Text(
                        'Esta versi\u00F3n no tiene avisos registrados.',
                      ),
                    if (warnings.isNotEmpty)
                      const Text(
                        'Esta versi\u00F3n incluye avisos sin un p\u00E1rrafo asignado.',
                      ),
                    if (warnings.isNotEmpty)
                      for (final warning in warnings)
                        ListTile(
                          title: Text(warningText(warning)),
                          subtitle: Text(
                            'Segmento ${warning['segment'] ?? 'sin identificar'}',
                          ),
                        ),
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: const Text('Cerrar'),
              ),
            ],
          ),
        );
        return;
      }

      if (sourceLines.isEmpty || sourceLines.length != rows.length) {
        throw StateError(
          'El original tiene ${sourceLines.length} l\u00EDneas con texto y la traducci\u00F3n '
          '${rows.length}. Esta versi\u00F3n requiere cotejo en el editor comparativo.',
        );
      }

      final visibleRows = [
        for (var i = 0; i < rows.length; i++)
          if (!onlyWarnings || byRow.containsKey(i)) i,
      ];
      final revised = List<String>.of(targetLines);
      final accepted = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Revisi\u00F3n biling\u00FCe'),
          content: SizedBox(
            width: 1000,
            height: 560,
            child: ListView.builder(
              itemCount: visibleRows.length,
              itemBuilder: (context, position) {
                final i = visibleRows[position];
                return Padding(
                  key: ValueKey(i),
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('P\u00E1rrafo ${i + 1}'),
                      for (final warning in byRow[i] ?? <Map>[])
                        Padding(
                          padding: const EdgeInsets.only(top: 6),
                          child: Text(
                            warningText(warning),
                            style: TextStyle(
                              color: Theme.of(context).colorScheme.error,
                            ),
                          ),
                        ),
                      const SizedBox(height: 8),
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(child: SelectableText(sourceLines[i])),
                          const SizedBox(width: 16),
                          Expanded(
                            child: TextFormField(
                              initialValue: revised[rows[i]].trimRight(),
                              minLines: 2,
                              maxLines: null,
                              decoration: const InputDecoration(
                                labelText: 'Ingl\u00E9s',
                              ),
                              onChanged: (value) => revised[rows[i]] = value,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancelar'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Guardar versi\u00F3n revisada'),
            ),
          ],
        ),
      );

      if (!mounted || accepted != true) return;
      if (rows.any((row) => revised[row].trim().isEmpty)) {
        throw StateError(
          'La revisi\u00F3n contiene un p\u00E1rrafo vac\u00EDo.',
        );
      }
      final text = revised.join('\n');
      if (text == target) {
        setState(() => status = 'Sin cambios para guardar');
        return;
      }

      final saved = await api.saveRevision(widget.projectId, mid, vid, text);
      if (!mounted) return;
      await loadVersion(saved['id'] as String);
      if (!mounted) return;
      final history = await api.versions(widget.projectId, mid);
      if (!mounted) return;
      setState(() {
        versions = history
            .where((v) => v is Map && v['chapter_index'] == index)
            .toList();
        status = 'Versi\u00F3n revisada guardada';
      });
    });
  }

  Future<void> loadVersion(String id) async {
    final mid = manuscriptId;
    if (mid == null) return;
    final result = await api.version(widget.projectId, mid, id);
    final text = result['translated_text'] ?? result['translation'];
    if (text is! String || text.trim().isEmpty) {
      throw StateError('La versión guardada no contiene texto traducido.');
    }
    if (mounted) {
      setState(() {
        translated.text = text;
        loadedVersionId = id;
        status = 'Versión recuperada: $id';
      });
    }
  }

  int? bookChapterNumber;
  int bookChapterTotal = 0;
  String? bookChapterTitle;

  Future<void> translateChapter() async {
    final mid = manuscriptId;
    final model = selectedModel;
    if (mid == null || model == null) {
      return;
    }
    await task(() => translateOneChapter(mid, chapterIndex, model));
  }

  Future<void> translateAllChapters() async {
    final mid = manuscriptId;
    final model = selectedModel;
    if (mid == null || model == null || chapters.isEmpty) {
      return;
    }
    final titles = [
      for (final chapter in chapters) '${chapter['title']}',
    ];
    await task(() async {
      final failures = <String>[];
      var saved = 0;
      try {
        for (var i = 0; i < titles.length; i++) {
          if (!mounted) {
            return;
          }
          setState(() {
            bookChapterNumber = i + 1;
            bookChapterTotal = titles.length;
            bookChapterTitle = titles[i];
          });
          try {
            await selectChapter(i);
            if (!mounted) {
              return;
            }
            await translateOneChapter(mid, i, model);
            saved++;
          } catch (error) {
            failures.add('${titles[i]}: $error');
          }
        }
      } finally {
        if (mounted) {
          setState(() {
            bookChapterNumber = null;
            bookChapterTitle = null;
            final summary = 'Libro: $saved de ${titles.length} capítulos guardados.';
            final pending = failures.join('\n');
            status = pending.isEmpty ? summary : '$summary\nPendientes:\n$pending';
          });
        }
      }
    });
  }

  Future<void> translateOneChapter(String mid, int index, String activeModel) async {
      final random = Random.secure();
      final digits = List.generate(
        32,
        (_) => random.nextInt(16).toRadixString(16),
      ).join();
      final jobId =
          '${digits.substring(0, 8)}-${digits.substring(8, 12)}-'
          '${digits.substring(12, 16)}-${digits.substring(16, 20)}-${digits.substring(20)}';
       final stopwatch = Stopwatch()..start();
      setState(() {
        completedSegments = 0;
        totalSegments = 0;
        translationElapsed = Duration.zero;
        translating = true;
        translationPercent = 0;
        status = 'Traduciendo con Ollama local…';
      });
      var polling = false;
      final timer = Timer.periodic(const Duration(seconds: 1), (timer) async {
        if (mounted) {
          setState(() => translationElapsed = stopwatch.elapsed);
        }
        if (polling) return;
        polling = true;
        try {
          final progress = await api.translationProgress(
            widget.projectId,
            mid,
            jobId,
          );
          if (!mounted || !timer.isActive) return;
          final total = progress['total'] as int;
          final completed = progress['completed'] as int;
          if (total > 0) {
            final percent = min(99, 100 * completed ~/ total);
            setState(() {
              translationPercent = max(translationPercent, percent);
              totalSegments = total;
              completedSegments = completed;
            });
          }
        } on Exception {
          // The translation request reports its own errors.
        } finally {
          polling = false;
        }
      });
      progressTimer = timer;
      try {
        final result = await api.translate(
          widget.projectId,
          mid,
          index,
          model: activeModel,
          jobId: jobId,
        );
        timer.cancel();
        if (!mounted) return;
        await loadVersion(result['id'] as String);
        if (!mounted) return;
        final history = await api.versions(widget.projectId, mid);
        if (!mounted) return;
        setState(() {
          versions = history
              .where((v) => v is Map && v['chapter_index'] == index)
              .toList();
          translationPercent = 100;
          status =
              'Borrador guardado. Segmentos: ${result['segments']}. '
              'Advertencias: ${(result['warnings'] as List?)?.length ?? 0}';
        });
      } finally {
        timer.cancel();
        if (mounted) setState(() => translating = false);
      }
  }

  Future<void> addGlossary() async {
    if (sourceTerm.text.trim().isEmpty || targetTerm.text.trim().isEmpty) {
      return;
    }
    await task(() async {
      await api.addTerm(
        widget.projectId,
        sourceTerm.text.trim(),
        targetTerm.text.trim(),
      );
      final found = await api.glossary(widget.projectId);
      if (mounted) {
        setState(() {
          terms = found;
          sourceTerm.clear();
          targetTerm.clear();
          status = 'Término registrado';
        });
      }
    });
  }

  Widget panel(
    String title,
    TextEditingController controller,
    Color color, {
    bool readOnly = true,
  }) => Expanded(
    child: Container(
      decoration: BoxDecoration(
        color: LiaTheme.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: color.withValues(alpha: .65)),
      ),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Icon(Icons.circle, color: color, size: 10),
                const SizedBox(width: 9),
                Text(
                  title,
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: TextField(
                controller: controller,
                readOnly: readOnly,
                expands: true,
                maxLines: null,
                minLines: null,
                style: const TextStyle(fontSize: 16, height: 1.6),
                decoration: const InputDecoration(
                  border: InputBorder.none,
                  filled: false,
                  hintText: 'El contenido aparecerá aquí...',
                ),
              ),
            ),
          ),
        ],
      ),
    ),
  );
  @override
  Widget build(BuildContext context) {
    final progressColor = translationPercent == 100
        ? const Color(0xFF69FF88)
        : Color.lerp(LiaTheme.cyan, LiaTheme.violet, translationPercent / 100)!;
    final narrow = MediaQuery.sizeOf(context).width < 1100;
    final nav = Container(
      width: 225,
      color: LiaTheme.surface,
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.all(12),
            child: Text(
              'MANUSCRITOS',
              style: TextStyle(color: LiaTheme.cyan, letterSpacing: 1.2),
            ),
          ),
          OutlinedButton.icon(
            onPressed: busy ? null : importFile,
            icon: const Icon(Icons.upload_file),
            label: const Text('IMPORTAR TXT / DOCX'),
          ),
          const SizedBox(height: 12),
          for (final m in manuscripts)
            ListTile(
              dense: true,
              selected: '${m['id']}' == manuscriptId,
              title: Text(
                '${m['filename']}',
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              onTap: busy
                  ? null
                  : () => task(() => selectManuscript('${m['id']}')),
            ),
          const Divider(),
          const Padding(
            padding: EdgeInsets.all(12),
            child: Text(
              'CAPÍTULOS',
              style: TextStyle(color: LiaTheme.cyan, letterSpacing: 1.2),
            ),
          ),
          Expanded(
            child: ListView.builder(
              itemCount: chapters.length,
              itemBuilder: (_, i) => ListTile(
                dense: true,
                selected: chapterIndex == i,
                leading: const Icon(Icons.article_outlined, size: 18),
                title: Text(
                  '${chapters[i]['title']}',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
                onTap: busy ? null : () => task(() => selectChapter(i)),
              ),
            ),
          ),
        ],
      ),
    );
    final settings = Container(
      width: narrow ? double.infinity : 300,
      padding: const EdgeInsets.all(18),
      color: LiaTheme.surface,
      child: ListView(
        children: [
          const Text(
            'PANEL DE TRADUCCIÓN',
            style: TextStyle(
              color: LiaTheme.violet,
              fontWeight: FontWeight.bold,
              letterSpacing: 1.1,
            ),
          ),
          const SizedBox(height: 22),
          const Text('Proveedor de IA'),
          const SizedBox(height: 8),
          const Card(
            child: ListTile(
              title: Text('Ollama (local)'),
              leading: Icon(Icons.memory, color: LiaTheme.cyan),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: InputDecorator(
                  decoration: const InputDecoration(labelText: 'Modelo local'),
                  child: DropdownButtonHideUnderline(
                    child: DropdownButton<String>(
                      isExpanded: true,
                      value: selectedModel,
                      hint: Text(loadingModels ? 'Buscando modelos…' : 'Elige un modelo'),
                      items: [
                        for (final name in installedModels)
                          DropdownMenuItem(
                            value: name,
                            child: Text(name, overflow: TextOverflow.ellipsis),
                          ),
                      ],
                      onChanged: busy || loadingModels || modelsError != null
                          ? null
                          : (value) => setState(() => selectedModel = value),
                    ),
                  ),
                ),
              ),
              IconButton(
                tooltip: 'Actualizar modelos',
                onPressed: busy || loadingModels ? null : refreshModels,
                icon: const Icon(Icons.refresh),
              ),
            ],
          ),
          if (modelsError != null)
            Text(modelsError!, style: TextStyle(color: Theme.of(context).colorScheme.error))
          else if (!loadingModels && installedModels.isEmpty)
            const Text('Ollama no tiene modelos instalados.'),
          const SizedBox(height: 20),
          const Text(
            'Glosario editorial',
            style: TextStyle(fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          for (final term in terms.take(15))
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Text(
                '${term['source']} → ${term['target']}',
                style: const TextStyle(fontSize: 13),
              ),
            ),
          TextField(
            controller: sourceTerm,
            decoration: const InputDecoration(labelText: 'Término original'),
          ),
          const SizedBox(height: 7),
          TextField(
            controller: targetTerm,
            decoration: const InputDecoration(labelText: 'Equivalencia EN-US'),
          ),
          TextButton.icon(
            onPressed: busy ? null : addGlossary,
            icon: const Icon(Icons.add),
            label: const Text('AÑADIR AL GLOSARIO'),
          ),
          const SizedBox(height: 18),
          FilledButton.icon(
            onPressed: busy || manuscriptId == null || selectedModel == null ||
                loadingModels || modelsError != null ? null : translateChapter,
            icon: const Icon(Icons.auto_awesome),
            label: Text(translating ? 'TRADUCIENDO…' : 'TRADUCIR CAPÍTULO'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: busy || manuscriptId == null || chapters.isEmpty ||
                    selectedModel == null || loadingModels || modelsError != null
                ? null : translateAllChapters,
            icon: const Icon(Icons.library_books_outlined),
            label: const Text('TRADUCIR TODOS LOS CAPÍTULOS'),
          ),
          const Padding(
            padding: EdgeInsets.only(top: 8, bottom: 8),
            child: Text(
              'Las cosas que valen la pena toman su tiempo. '
              'Deja que LIA-Manuscript traduzca tu manuscrito.',
              style: TextStyle(fontSize: 12),
            ),
          ),
          if (bookChapterNumber != null)
            Text('Libro: $bookChapterNumber de $bookChapterTotal · $bookChapterTitle'),
          if (translating || translationPercent == 100) ...[
            const SizedBox(height: 14),
            LinearProgressIndicator(
              value: translating && translationPercent == 0 ? null : translationPercent / 100,
              color: progressColor,
              semanticsLabel: 'Progreso de traducción',
            ),
            Text(
              translating
                  ? totalSegments == 0
                      ? 'Preparando con $selectedModel · ${translationElapsed.inSeconds} s'
                      : '$completedSegments de $totalSegments segmentos · ${translationElapsed.inSeconds} s'
                  : '$translationPercent%',
              style: TextStyle(color: progressColor),
            ),
          ],
          const SizedBox(height: 22),
          const Text(
            'VERSIONES GUARDADAS',
            style: TextStyle(
              color: LiaTheme.violet,
              fontWeight: FontWeight.bold,
            ),
          ),

          OutlinedButton.icon(
            onPressed: busy || loadedVersionId == null ? null : reviewVersion,
            icon: const Icon(Icons.edit_note),
            label: const Text('REVISAR POR P\u00C1RRAFO'),
          ),
          OutlinedButton.icon(
            onPressed: busy || loadedVersionId == null
                ? null
                : () => reviewVersion(onlyWarnings: true),
            icon: const Icon(Icons.flag_outlined),
            label: const Text('SOLO P\u00C1RRAFOS CON AVISOS'),
          ),

          OutlinedButton.icon(
            onPressed: busy || loadedVersionId == null
                ? null
                : reviewAmericanEnglish,
            icon: const Icon(Icons.spellcheck),
            label: const Text('REVISAR INGL\u00C9S EN-US'),
          ),

          OutlinedButton.icon(
            onPressed: busy || loadedVersionId == null ? null : exportSavedDocx,
            icon: const Icon(Icons.file_download_outlined),
            label: const Text('EXPORTAR DOCX'),
          ),
          for (final v in versions)
            ListTile(
              dense: true,
              title: Text('Versión ${'${v['id']}'.substring(0, 8)}'),
              subtitle: Text('${v['created_at'] ?? ''}'),
              onTap: busy ? null : () => task(() => loadVersion('${v['id']}')),
            ),
          const SizedBox(height: 20),
          Text(
            status,
            style: const TextStyle(color: LiaTheme.muted, fontSize: 12),
          ),
        ],
      ),
    );
    final editor = Expanded(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          children: [
            Row(
              children: [
                const Icon(Icons.compare_arrows, color: LiaTheme.cyan),
                const SizedBox(width: 8),
                const Text(
                  'EDITOR COMPARATIVO',
                  style: TextStyle(fontWeight: FontWeight.bold),
                ),
                const Spacer(),
                Text(
                  chapters.isEmpty
                      ? 'Sin capítulos'
                      : '${chapters[chapterIndex]['title']}',
                  style: const TextStyle(color: LiaTheme.muted),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Expanded(
              child: Row(
                children: [
                  panel('ORIGINAL · ESPAÑOL', original, LiaTheme.cyan),
                  const SizedBox(width: 12),
                  panel('TRADUCCIÓN · EN-US', translated, LiaTheme.violet),
                ],
              ),
            ),
          ],
        ),
      ),
    );
    return Scaffold(
      appBar: AppBar(
        title: Text('LIA MANUSCRIPT  /  ${widget.projectName}'),
        actions: [
          const Padding(
            padding: EdgeInsets.only(right: 20),
            child: Center(
              child: Text(
                'DATOS REALES · SQLITE',
                style: TextStyle(color: LiaTheme.violet, fontSize: 12),
              ),
            ),
          ),
        ],
      ),
      body: narrow
          ? Row(children: [nav, editor])
          : Row(children: [nav, editor, settings]),
      bottomNavigationBar: narrow
          ? SizedBox(height: 260, child: settings)
          : null,
    );
  }
}
