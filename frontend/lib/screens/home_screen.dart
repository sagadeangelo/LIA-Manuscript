import 'package:flutter/material.dart';
import '../core/services/api_service.dart';
import '../core/theme/lia_theme.dart';
import 'editor_screen.dart';

class HomeScreen extends StatefulWidget { const HomeScreen({super.key}); @override State<HomeScreen> createState()=>_HomeScreenState(); }
class _HomeScreenState extends State<HomeScreen> {
  final api=const ApiService(); bool busy=false; bool online=false; String? error; List<dynamic> projects=[];
  @override void initState(){super.initState(); refresh();}
  Future<void> refresh() async {
    setState((){busy=true;error=null;});
    try { final ok=await api.isOnline(); final found=ok?await api.projects():<dynamic>[]; if(mounted)setState((){online=ok;projects=found;}); }
    catch(e){if(mounted)setState((){online=false;error='$e';});}
    finally {if(mounted)setState(()=>busy=false);}
  }
  Future<void> create() async {
    final controller=TextEditingController();
    final name=await showDialog<String>(context:context,builder:(ctx)=>AlertDialog(title:const Text('Nuevo proyecto'),content:TextField(controller:controller,autofocus:true,decoration:const InputDecoration(hintText:'Título del manuscrito')),actions:[TextButton(onPressed:()=>Navigator.pop(ctx),child:const Text('Cancelar')),FilledButton(onPressed:()=>Navigator.pop(ctx,controller.text.trim()),child:const Text('Crear'))]));
    controller.dispose(); if(name==null||name.isEmpty)return;
    try {await api.createProject(name); await refresh();}catch(e){if(mounted)ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:Text('$e')));}
  }
  @override Widget build(BuildContext context)=>Scaffold(
    appBar:AppBar(title:const Text('LIA  /  MANUSCRIPT',style:TextStyle(fontWeight:FontWeight.bold,letterSpacing:2)),actions:[IconButton(onPressed:refresh,icon:const Icon(Icons.refresh))]),
    body:Padding(padding:const EdgeInsets.all(28),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
      const Text('Estudio de traducción literaria',style:TextStyle(fontSize:29,fontWeight:FontWeight.bold)),const SizedBox(height:6),
      const Text('Español → Inglés estadounidense · Editor comparativo',style:TextStyle(color:LiaTheme.muted)),const SizedBox(height:26),
      Card(child:ListTile(leading:Icon(online?Icons.cloud_done:Icons.cloud_off,color:online?LiaTheme.cyan:Colors.orange),title:Text(online?'Backend disponible en 127.0.0.1:8102':'Backend no disponible'),trailing:TextButton(onPressed:refresh,child:const Text('REINTENTAR')))),
      if(error!=null)Padding(padding:const EdgeInsets.all(8),child:Text(error!,style:const TextStyle(color:Colors.orange))),const SizedBox(height:24),
      Row(children:[const Text('Proyectos',style:TextStyle(fontSize:23,fontWeight:FontWeight.bold)),const Spacer(),FilledButton.icon(onPressed:online&&!busy?create:null,icon:const Icon(Icons.add),label:const Text('NUEVO PROYECTO'))]),const SizedBox(height:14),
      Expanded(
        child: busy
            ? const Center(child: CircularProgressIndicator())
            : projects.isEmpty
                ? const Center(
                    child: Text(
                      'No hay proyectos. Crea uno para importar un manuscrito.',
                      style: TextStyle(color: LiaTheme.muted),
                    ),
                  )
                : ListView.builder(
                    itemCount: projects.length,
                    itemBuilder: (context, i) {
                      final p = Map<String, dynamic>.from(projects[i]);
                      return Card(
                        child: ListTile(
                          leading: const Icon(Icons.menu_book, color: LiaTheme.cyan),
                          title: Text('${p['name']}'),
                          subtitle: Text('ID: ${p['id']}'),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () => Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) => EditorScreen(
                                projectId: '${p['id']}',
                                projectName: '${p['name']}',
                              ),
                            ),
                          ),
                        ),
                      );
                    },
                  ),
                  ),
    ])));
}
