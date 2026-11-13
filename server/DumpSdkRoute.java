import com.sun.jdi.*;
import com.sun.jdi.connect.*;
import java.util.*;
import java.nio.file.*;

public class DumpSdkRoute {
    static Value field(ObjectReference object,String name) {
        Field f=object.referenceType().fieldByName(name);
        return f==null?null:object.getValue(f);
    }
    public static void main(String[] argv) throws Exception {
        AttachingConnector connector=Bootstrap.virtualMachineManager().attachingConnectors().stream()
            .filter(c->c.name().equals("com.sun.jdi.SocketAttach")).findFirst().get();
        Map<String,Connector.Argument> args=connector.defaultArguments();
        args.get("hostname").setValue("127.0.0.1");args.get("port").setValue("8700");
        VirtualMachine vm=connector.attach(args);
        try {
            vm.suspend();
            ReferenceType sdk=vm.classesByName("com.tmapmobility.tmap.tmapsdk.ui.util.TmapUISDK").get(0);
            ObjectReference live=(ObjectReference)sdk.getValue(sdk.fieldByName("observableRouteData"));
            ObjectReference data=(ObjectReference)field(live,"mData");
            System.out.println("Route data type: "+data.referenceType().name());
            for(Field f:data.referenceType().allFields())System.out.println(f.name()+" : "+f.typeName());
            ObjectReference coords=(ObjectReference)field(data,"e");
            System.out.println("Coordinate collection: "+coords.referenceType().name());
            for(Field f:coords.referenceType().allFields())System.out.println("Collection field: "+f.name()+" : "+f.typeName());
            int count=((IntegerValue)field(coords,"size")).value();
            ArrayReference array=(ArrayReference)field(coords,"elementData");
            StringBuilder json=new StringBuilder("{\"source\":\"active TMAP observableRouteData\",\"segments\":[[");
            for(int index=0;index<count;index++) {
                ObjectReference point=(ObjectReference)array.getValue(index);
                if(index>0)json.append(',');
                json.append('[').append(((DoubleValue)field(point,"a")).value()).append(',')
                    .append(((DoubleValue)field(point,"b")).value()).append(']');
            }
            json.append("]],\"roads\":[");
            ObjectReference roads=(ObjectReference)field(data,"g");
            int roadCount=roads==null?0:((IntegerValue)field(roads,"size")).value();
            ArrayReference roadArray=roads==null?null:(ArrayReference)field(roads,"elementData");
            for(int index=0;index<roadCount;index++) {
                ObjectReference road=(ObjectReference)roadArray.getValue(index);
                if(index>0)json.append(',');
                json.append("{\"start_index\":").append(((IntegerValue)field(road,"startVtxIndex")).value())
                    .append(",\"end_index\":").append(((IntegerValue)field(road,"endVtxIndex")).value())
                    .append(",\"limit_kph\":").append(((IntegerValue)field(road,"maxSpeedKmh")).value()).append('}');
            }
            json.append("]}");Files.writeString(Path.of("build/active-sdk-route.json"),json.toString());
            System.out.println("SDK route points saved: "+count);
            System.out.println("SDK road speed sections saved: "+roadCount);
        } finally { vm.resume();vm.dispose(); }
    }
}
