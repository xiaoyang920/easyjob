package com.easyjob.utils;


import com.easyjob.exception.BusinessException;
import org.apache.commons.codec.digest.DigestUtils;


import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.Random;


public class StringTools {

    public static void checkParam(Object param) {
        try {
            Field[] fields = param.getClass().getDeclaredFields();
            boolean notEmpty = false;
            for (Field field : fields) {
                String methodName = "get" + StringTools.upperCaseFirstLetter(field.getName());
                Method method = param.getClass().getMethod(methodName);
                Object object = method.invoke(param);
                if (object != null && object instanceof String && !StringTools.isEmpty(object.toString())
                        || object != null && !(object instanceof String)) {
                    notEmpty = true;
                    break;
                }
            }
            if (!notEmpty) {
                throw new BusinessException("多参数更新，删除，必须有非空条件");
            }
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            e.printStackTrace();
            throw new BusinessException("校验参数是否为空失败");
        }
    }

    public static String upperCaseFirstLetter(String field) {
        if (isEmpty(field)) {
            return field;
        }
        //如果第二个字母是大写，第一个字母不大写
        if (field.length() > 1 && Character.isUpperCase(field.charAt(1))) {
            return field;
        }
        return field.substring(0, 1).toUpperCase() + field.substring(1);
    }

    public static boolean isEmpty(String str) {
        if (null == str || "".equals(str) || "null".equals(str) || "\u0000".equals(str)) {
            return true;
        } else if ("".equals(str.trim())) {
            return true;
        }
        return false;
    }

    public static String encodByMd5(String registerPassword) {
        return StringTools.isEmpty(registerPassword)?null:DigestUtils.md5Hex(registerPassword.getBytes(StandardCharsets.UTF_8));
    }

    /**
     * 路径是否合法
     * @param path
     * @return
     */
    public static boolean pathIsOk(String path){
        if (StringTools.isEmpty( path)){
            return true;
        }
        if(path.contains("../")||path.contains("..\\")){
            return false;
        }
        return true;
    }
    /**
     * 获取文件名后缀
     */
    public static String getFileSuffix(String fileName) {
        if(StringTools.isEmpty(fileName)||!fileName.contains(".")){
            return null;
        }
        String suffix = fileName.substring(fileName.lastIndexOf("."));
        return suffix;
    }
    public static String code(Integer lenght){
        Random random = new Random();
        StringBuilder code = new StringBuilder();
        for (int i = 0; i < lenght; i++) {
            code.append(random.nextInt(10));
        }
        return code.toString();
    }
}
