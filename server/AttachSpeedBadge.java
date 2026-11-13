import com.sun.jdi.*;
import com.sun.jdi.connect.*;
import com.sun.jdi.event.*;
import com.sun.jdi.request.*;
import java.util.*;

/** Debug-only: load the same app badge into an existing session, avoiding APK reinstall/route requests. */
public final class AttachSpeedBadge {
    public static void main(String[] argv) throws Exception {
        AttachingConnector connector=Bootstrap.virtualMachineManager().attachingConnectors().stream()
            .filter(c->c.name().equals("com.sun.jdi.SocketAttach")).findFirst().get();
        Map<String,Connector.Argument> args=connector.defaultArguments();
        args.get("hostname").setValue("127.0.0.1");args.get("port").setValue("8700");
        VirtualMachine vm=connector.attach(args);BreakpointRequest breakpoint=null;EventSet paused=null;
        try {
            ReferenceType activityType=vm.classesByName("com.example.pleosprojectv01.NativeTmapActivity").get(0);
            Location location=activityType.methodsByName("pollCompanions").get(0).allLineLocations().get(0);
            breakpoint=vm.eventRequestManager().createBreakpointRequest(location);
            breakpoint.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);breakpoint.enable();
            long deadline=System.currentTimeMillis()+15000;ThreadReference thread=null;
            while(System.currentTimeMillis()<deadline && thread==null) {
                EventSet set=vm.eventQueue().remove(3000);if(set==null)continue;
                for(Event event:set)if(event instanceof BreakpointEvent) {thread=((BreakpointEvent)event).thread();paused=set;}
                if(thread==null)set.resume();
            }
            if(thread==null)throw new IllegalStateException("Navigation UI did not reach its next poll");
            System.out.println("Paused at "+location.sourceName()+":"+location.lineNumber());
            for(StackFrame frame:thread.frames(0,Math.min(3,thread.frameCount())))System.out.println(frame.location().method().name());
            ObjectReference activity=thread.frame(0).thisObject();
            ClassLoaderReference parent=activity.referenceType().classLoader();
            Method load=parent.referenceType().methodsByName("loadClass","(Ljava/lang/String;)Ljava/lang/Class;").get(0);
            ClassType loaderType=(ClassType)((ClassObjectReference)parent.invokeMethod(thread,load,
                Arrays.asList(vm.mirrorOf("dalvik.system.DexClassLoader")),ObjectReference.INVOKE_SINGLE_THREADED)).reflectedType();
            Method constructor=loaderType.methodsByName("<init>","(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/ClassLoader;)V").get(0);
            String base="/data/user/10/com.example.pleosprojectv01.convoy/";
            ObjectReference loader=loaderType.newInstance(thread,constructor,Arrays.asList(
                vm.mirrorOf(base+"files/live-speed-badge.dex"),vm.mirrorOf(base+"code_cache"),null,parent),ObjectReference.INVOKE_SINGLE_THREADED);
            ClassType badge=(ClassType)((ClassObjectReference)loader.invokeMethod(thread,load,
                Arrays.asList(vm.mirrorOf("com.example.pleosprojectv01.SpeedLimitBadge")),ObjectReference.INVOKE_SINGLE_THREADED)).reflectedType();
            loader.invokeMethod(thread,load,Arrays.asList(vm.mirrorOf("android.app.Activity")),ObjectReference.INVOKE_SINGLE_THREADED);
            // ART's JDWP visible-class list can omit parent-loader signature types.
            // Java reflection resolves the public Activity parameter in the VM instead.
            ClassObjectReference badgeClass=badge.classObject();
            ArrayReference methods=(ArrayReference)badgeClass.invokeMethod(thread,badgeClass.referenceType()
                .methodsByName("getDeclaredMethods","()[Ljava/lang/reflect/Method;").get(0),Collections.emptyList(),ObjectReference.INVOKE_SINGLE_THREADED);
            ObjectReference attach=null;
            for(Value value:methods.getValues()) {
                ObjectReference method=(ObjectReference)value;
                StringReference name=(StringReference)method.invokeMethod(thread,method.referenceType()
                    .methodsByName("getName","()Ljava/lang/String;").get(0),Collections.emptyList(),ObjectReference.INVOKE_SINGLE_THREADED);
                if(name.value().equals("attach")) {attach=method;break;}
            }
            if(attach==null)throw new IllegalStateException("Public badge attach method missing");
            ArrayReference parameters=((ArrayType)vm.classesByName("java.lang.Object[]").get(0)).newInstance(1);
            parameters.setValue(0,activity);
            attach.invokeMethod(thread,attach.referenceType().methodsByName("invoke","(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;").get(0),
                Arrays.asList(null,parameters),ObjectReference.INVOKE_SINGLE_THREADED);
            System.out.println("Attached actual app SpeedLimitBadge; no activity restart or route request");
        } finally {
            if(breakpoint!=null)vm.eventRequestManager().deleteEventRequest(breakpoint);
            if(paused!=null)paused.resume();
            vm.dispose();
        }
    }
}
