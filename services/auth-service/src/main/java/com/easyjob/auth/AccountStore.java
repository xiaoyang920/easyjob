package com.easyjob.auth;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;
import java.util.*;
import com.easyjob.auth.AccountStore.Account;
import java.util.List;
import java.util.Map;

@Repository
public class AccountStore {
    private final JdbcTemplate db;
    public AccountStore(JdbcTemplate db){this.db=db;}
    public record Account(long id,String email,String password,String name,String avatar,int role,int status,long version){}
    private Account row(java.sql.ResultSet r,int index)throws java.sql.SQLException{return new Account(r.getLong("user_id"),r.getString("email"),r.getString("password"),r.getString("nick_name"),r.getString("avatar"),r.getInt("role"),r.getInt("status"),r.getLong("auth_version"));}
    private static final String FIELDS="user_id,email,password,nick_name,avatar,role,status,auth_version";
    public Account byId(long uid){List<Account> rows=db.query("SELECT "+FIELDS+" FROM user_info WHERE user_id=?",this::row,uid);return rows.isEmpty()?null:rows.getFirst();}
    public Account byEmail(String email){List<Account> rows=db.query("SELECT "+FIELDS+" FROM user_info WHERE email=?",this::row,email);return rows.isEmpty()?null:rows.getFirst();}
    @Transactional public Account register(long id,String email,String name,String hash){
        if(!db.queryForList("SELECT user_id FROM user_info WHERE email=? OR nick_name=? LIMIT 1",email,name).isEmpty())throw new AuthFailure(409,"邮箱或昵称已被使用");
        db.update("""
            INSERT INTO user_info(user_id,email,password,nick_name,status,role,auth_version,join_time,last_login_time,
              total_coin_count,current_coin_count,article_count,follower_count,following_count,theme)
            VALUES(?,?,?,?,1,1,0,NOW(),NOW(),10,10,0,0,0,1)
            """,id,email,hash,name);
        return byId(id);
    }
    public Account upgrade(Account old,String hash){db.update("UPDATE user_info SET password=? WHERE user_id=? AND password=?",hash,old.id(),old.password());return byId(old.id());}
    public void touch(long uid){db.update("UPDATE user_info SET last_login_time=NOW() WHERE user_id=?",uid);}
    @Transactional public void password(Account expected,String hash,String action){
        int n=db.update("UPDATE user_info SET password=?,auth_version=COALESCE(auth_version,0)+1 WHERE user_id=? AND auth_version=? AND password=? AND status=1",hash,expected.id(),expected.version(),expected.password());
        if(n!=1)throw new AuthFailure(409,"账号已变化，请重试");
        audit(UUID.randomUUID().toString(),expected.id(),expected.id(),action,expected.version()+1);
        outbox(expected.id(),null,expected.version()+1);
    }
    @Transactional public void security(long actor,long target,long expectedVersion,int role,int status,String command,String reason){
        List<Account> rows=db.query("SELECT "+FIELDS+" FROM user_info WHERE user_id IN (?,?) ORDER BY user_id FOR UPDATE",this::row,actor,target);
        Account operator=rows.stream().filter(a->a.id()==actor).findFirst().orElse(null),user=rows.stream().filter(a->a.id()==target).findFirst().orElse(null);
        if(operator==null||operator.status()!=1||operator.role()!=2)throw new AuthFailure(403,"管理员权限已变化");
        if(user==null)throw new AuthFailure(404,"用户不存在");
        String signature=Sessions.digest(actor+":"+target+":"+expectedVersion+":"+role+":"+status+":"+reason);
        List<Map<String, Object>> prior=db.queryForList("SELECT details FROM auth_audit WHERE command_id=?",command);
        if(!prior.isEmpty()){if(!signature.equals(prior.getFirst().get("details")))throw new AuthFailure(409,"操作编号已被使用");return;}
        if(user.version()!=expectedVersion)throw new AuthFailure(409,"账号安全设置已变化，请重新加载");
        if(actor==target&&(role!=2||status!=1))throw new AuthFailure(409,"不能取消自己的管理员身份或禁用自己的账号");
        if(!Set.of(1,2,3,4).contains(role)||(status!=0&&status!=1))throw new AuthFailure(400,"角色或状态无效");
        db.update("UPDATE user_info SET role=?,status=?,auth_version=auth_version+1 WHERE user_id=?",role,status,target);
        db.update("INSERT INTO auth_audit(command_id,actor_id,target_id,action,details,reason,created_at) VALUES(?,?,?,'security_change',?,?,UTC_TIMESTAMP(6))",command,actor,target,signature,reason);
        outbox(target,null,user.version()+1);
    }
    private void audit(String command,long actor,long target,String action,long version){db.update("INSERT INTO auth_audit(command_id,actor_id,target_id,action,details,created_at) VALUES(?,?,?,?,?,UTC_TIMESTAMP(6))",command,actor,target,action,Long.toString(version));}
    private void outbox(long uid,String sid,long version){db.update("INSERT INTO auth_outbox(event_id,user_id,sid,auth_version,created_at,next_attempt_at) VALUES(?,?,?,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",UUID.randomUUID().toString(),uid,sid,version);}
    public void schema(){db.queryForList("SELECT command_id FROM auth_audit WHERE 1=0");db.queryForList("SELECT event_id FROM auth_outbox WHERE 1=0");}
}
