
package com.easyjob.mapper;

import javax.sql.DataSource;
import org.apache.ibatis.session.Configuration;
import org.apache.ibatis.session.SqlSessionFactory;
import org.mybatis.spring.SqlSessionFactoryBean;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.core.io.ClassPathResource;

/** Integration tests use the same Spring-managed MyBatis transaction participation. */
public final class MapperTestSupport {
    private MapperTestSupport() {}
    public static <T> T mapper(DataSource dataSource, Class<T> contract) {
        try {
            Configuration configuration = new Configuration();
            configuration.setMapUnderscoreToCamelCase(true);
            SqlSessionFactoryBean factory = new SqlSessionFactoryBean();
            factory.setDataSource(dataSource);
            factory.setConfiguration(configuration);
            factory.setMapperLocations(new ClassPathResource("mapper/" + contract.getSimpleName() + ".xml"));
            SqlSessionFactory sessions = java.util.Objects.requireNonNull(factory.getObject());
            return new SqlSessionTemplate(sessions).getMapper(contract);
        } catch (Exception failure) {
            throw new IllegalStateException("Cannot initialize mapper integration fixture", failure);
        }
    }
}
